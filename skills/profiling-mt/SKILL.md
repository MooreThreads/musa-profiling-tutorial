---
name: profiling-mt
version: 1.0.1
description: 摩尔线程 GPU 性能分析技能 - 使用 Moore Perf System 和 Moore Perf Compute 进行性能数据采集、瓶颈分析和优化指导；使用 Moore Perf Compute 在 PH1 架构上分析 MUSA kernel。当用户提到 GPU profiling、性能分析、性能剖析、性能瓶颈、性能优化、调优、kernel 性能分析、性能指标、Moore Perf System、Moore Perf Compute、msys、mcu、Moore Perf、MUSA GPU 性能分析，或要求 "profile 一下"、"为什么慢"、分析 "mcu 报告"、给出优化方案时使用。
---

# Profiling-MT | 摩尔线程 GPU 性能分析

## 触发条件

当用户提到以下关键词时使用此技能：
- GPU profiling、性能分析、性能剖析
- 性能瓶颈、性能优化、调优
- kernel 性能分析、性能指标
- msys、mcu、Moore Perf
- MUSA GPU 性能分析

同时覆盖以下触发说法：
- 要求 profile 一个 MUSA kernel、分析其性能、定位瓶颈，或基于 Moore Perf Compute 数据写优化方案
- "profile X"、"为什么这个 kernel 慢"、"mcu report 说..."、"下一步怎么优化"、"帮我看一下这份 mcu 报告"、"profile 一下"、"为什么慢"、"mcu 报告"

## 总体工作流

### 职责与执行原则

本技能负责环境检查、固定 workload、运行程序、采集和解析 `msys`/`mcu` 性能数据，并将可复现的证据交给 coding agent；coding agent 根据这些证据在隔离副本中实现和验证候选优化。只有用户明确授权修改项目源码后，才把验证通过的候选改动应用到原始源码。技能可以提供通用及 PH1 相关的编程参考来辅助判断，但不能用经验规则代替实际 profiling 数据。

### 门禁命令（强制，先于任何优化）

是否允许优化由 [`profiling/scripts/gate.py`](profiling/scripts/gate.py) 判定，不由模型自行判断。该脚本只读 run 目录，不采集数据。

```bash
python3 <skill_dir>/profiling/scripts/gate.py <run 目录>
```

- 退出码 `0` 且输出 `"optimization_allowed": true`：基线成立，可以进入本文件后续流程。
- 退出码 `2` 或 `"status": "blocked"`：立即停止优化。不得修改、生成或应用任何优化代码；只执行输出里 `required_action` 指向的补采动作，把产出放进同一 run 目录后重新运行本命令。
- 优化开始前必须先把每个项目原始文件登记进门禁：`python3 gate.py --snapshot-source <原始文件> <run 目录>`。可重复传入 `--snapshot-source`。之后每次运行都会校验 SHA-256。
- `sources_unchanged=false` 时，原始文件已被改动。立即用隔离副本中的优化前内容恢复这些文件，然后重新运行门禁。不得继续编辑 `source-manifest.json` 记录的文件。
- “生成 patch”“测试并优化”“直接改到能运行”都不等于写入授权。候选改动和 patch 只能写到隔离副本或用户指定的实验目录；在用户明确授权前，不得应用到项目原始文件。
- 开始优化前运行一次。此后每轮候选改动在验证正确性之后、决定保留或回退之前，再对同一目录运行一次。
- 空报告、采集报错、只有 warning、或导出里没有目标活动记录时，脚本返回 `blocked`。程序自带计时、手工微基准和上一轮的数据都不能代替这次命令结果。

run 目录至少要包含：

| 文件 | 来源 |
|---|---|
| `<name>.msys-rep` | `msys profile -o <name> ...` |
| `<name>_musa_gpu_kern_sum.json` 或 `<name>_musa_api_sum.json` | `msys stats -f json -r <类型> -o <name> <name>.msys-rep` |
| `<name>.mcu-rep` | `mcu` 采集 |
| `details_<name>.txt` | `mcu --import <name>.mcu-rep --page details` |
| `raw_<name>.csv` | `mcu --import <name>.mcu-rep --page raw --csv` |

#### 源码变更边界（强制）

默认将用户提供的项目源码视为**只读输入**。除非用户明确要求“应用优化到源码”“直接修改指定文件”或给出同等明确的写入授权，否则：

1. baseline 和优化候选都必须复制到独立的 `profile/<run_name>/harness/`、独立 worktree，或用户指定的实验目录（例如远端 `/tmp/<run_name>/`）中；不得在原始源码目录内就地修改。
2. 编译、运行、profiling 和候选代码迭代只能针对上述隔离副本；使用现有二进制做 profile 时也不得借机改写其源文件。
3. 完成后只交付候选 patch/diff、正确性结果、before/after 数据、artifact 路径和是否建议应用；在获得用户确认前，不把候选 patch 应用回项目源码。
4. “测试和优化”“profile 一下”“帮我调优”“给出优化方案”等表述只授权分析和隔离验证，**不等价于授权修改原始源码**。
5. 用户指定实验路径（例如 `/tmp`）时，该路径同时是默认的构建、运行和候选修改边界；不能因为实验发生在远端，就先修改本地原始源码再复制过去。
6. 若现有仓库已有未提交或已暂存改动，不覆盖、不回退、不混入候选优化；先记录状态，并在独立副本中工作。

只有收到明确写入授权后，才能将已验证的候选改动应用到用户指定的原始文件；应用前说明将修改哪些文件，应用后展示 diff 并重新执行正确性与性能验证。

#### 基线报告门禁（强制）

建立基线时必须实际尝试用 `msys` 和 `mcu` 各采集一次，并判定报告是否有效。命令能启动、进程退出码为 0，或磁盘上出现一个文件，都不等于报告有效。

1. `msys` 有效：生成非空 `.msys-rep`，且 `msys stats` 能解析出目标程序的 kernel、内存拷贝或 API 记录。空报告、只有报错文本、或 stats 无法列出任何目标活动，都是无效报告。
2. `mcu` 有效：生成非空 `.mcu-rep`，`--page details` 含有目标 kernel 的 section 和指标值，并且 `--page raw` 能导出包含该 kernel 指标名和值的 CSV。`mcu cannot be used in the current environment`、权限拒绝、被其他 profiler 占用、只有 warning 没有指标，都是无效报告。
3. 两个工具都要在基线 workload 上试到得出有效或无效的结论。不得只采到其中一个就进入优化，也不得因为另一个“按流程稍后再采”而跳过。
4. 任一工具没有有效报告时，立即停止优化。向用户说明哪个工具不可用、已执行的命令、原始错误和报告路径，并明确后续优化缺少该证据，结果不可靠。等待用户处理环境或明确指示后再继续。
5. 不得用应用自带计时、经验判断或另一工具的数据代替缺失报告继续修改代码。已有计时只能作为环境失败说明的补充，不能成为优化依据。

基线两份报告都有效后，再按热点选择后续路径：通常先用 `msys` 做系统级筛选，判断主要卡点属于 CPU、主机↔设备传输还是 GPU；只有已知目标 kernel，或 `msys` 已确认 MUSA kernel 是待优化热点时，才用 `mcu` 深挖单个 kernel。每轮优化固定输入、设备和测量方法，尽量只改变一个主要变量，先验证正确性，再依据同负载 before/after 数据决定保留或回退；观测到同时变化但缺乏因果证据的指标，不归因于当前改动。

根据输入选择最短且证据充分的路径，而不是机械地同时运行 `msys` 和 `mcu`：

1. **完整程序、热点未知：先 `msys`。** 基线门禁已经要求 `msys` 和 `mcu` 都有有效报告。之后用 [`profiling/msys-usage.md`](profiling/msys-usage.md) 的系统级报告，按 [`profiling/msys-analysis.md`](profiling/msys-analysis.md) 区分 CPU、主机↔设备传输和 GPU kernel 热点。CPU/传输是主要卡点时，后续迭代停留在系统级证据，不为每一轮凑流程重复采 `mcu`。
2. **目标 kernel 已知，或 `msys` 已确认 kernel 热点：进入 `mcu-report/`。** 按 [`mcu-report/reference/01-workflow.md`](mcu-report/reference/01-workflow.md) 固定 workload 和 dispatch path，采集报告、先读完整 details、再读 raw 指标，完成六维分析和诊断。不能只采一份报告或看一两个吞吐率就直接改代码。
3. **已有报告：直接导入，不重复采集。** `.msys-rep` 走系统级分析；`.mcu-rep` 按 [`mcu-report/reference/04-report-cli.md`](mcu-report/reference/04-report-cli.md) 提取 details/raw，并按 [`05-analysis-dimensions.md`](mcu-report/reference/05-analysis-dimensions.md) 分析。只有缺少回答当前问题所需的数据时才补采。
4. **优化闭环：一次只验证一项主要改动。** coding agent 默认只在隔离副本中实施一项主要改动，先做正确性验证，再以相同 workload 比较 before/after。端到端收益用 `msys` 或应用基准衡量；关键 kernel 的指标变化用 `mcu` 复核。不要把 Moore Perf Compute replay 时长直接当作应用耗时。没有明确源码写入授权时，闭环止于候选 patch 和证据交付，不应用回原始源码。

基线阶段的 `msys` 或 `mcu` 没有有效报告时，按上面的门禁停止并提示用户，不得继续优化。基线已成立后，若某一轮 `mcu` 缺少指标，只记录该轮证据边界；不得据此推断硬件瓶颈，也不得声称完成了 Moore Perf Compute 诊断。

## 任务路由

### A. 分析完整程序

1. 创建独立运行目录并固定输入、软件版本和设备状态；将所需源码复制到隔离副本，保持项目原始源码只读。
2. 先完成基线报告门禁：同一 workload 上必须同时拿到有效 `msys` 报告和有效 `mcu` 报告。任一报告无效时停止并提示用户，不进入后续优化。
3. 门禁通过后，用 `msys` 分析 gap、timeline 和 stats，确定主要时间花在 CPU、传输还是 GPU kernel。
4. 若目标是 CPU/传输，依据系统级证据优化并用同负载复测。
5. 若目标是 MUSA kernel，记录 kernel 名称、调用频次、耗时、workload 和 dispatch path，作为进入 `mcu-report/` 的交接信息。
6. 按 Moore Perf Compute workflow 形成有指标证据的诊断；coding agent 每轮只在隔离副本中实施一项主要改动，验证正确性后分别复测 kernel 和端到端结果。未获明确授权时，只交付候选 patch 和证据，不修改项目原始源码。

### B. 分析已知 kernel

已知 kernel 也不能跳过基线门禁。执行 [`mcu-report/reference/01-workflow.md`](mcu-report/reference/01-workflow.md) 前，仍要用同一 workload 拿到有效 `mcu` 报告和有效 `msys` 报告；任一报告无效时停止并提示用户：

1. 明确 kernel、真实 workload、dispatch path、问题和 baseline。
2. 读取 [`00-directory-layout.md`](mcu-report/reference/00-directory-layout.md) 并创建新 run。
3. 按 [`02-harness-guide.md`](mcu-report/reference/02-harness-guide.md) 决定使用独立 harness 还是现有二进制。
4. 按 [`03-collection.md`](mcu-report/reference/03-collection.md) 采集，再按 [`04-report-cli.md`](mcu-report/reference/04-report-cli.md) 提取 details/raw。
5. 逐项检查 [`05-analysis-dimensions.md`](mcu-report/reference/05-analysis-dimensions.md)，并用 [`06-diagnosis-playbook.md`](mcu-report/reference/06-diagnosis-playbook.md) 将实际指标映射为诊断与候选改动。
6. 按 [`07-report-template.md`](mcu-report/reference/07-report-template.md) 记录证据、预期、置信度和无法判断之处。

### C. 直接分析报告

#### `.msys-rep`

1. 先分析 GPU gap。
2. 无论 gap 是否明显，都继续运行脚本化 stats 深挖。
3. 输出现象、stats/timeline 证据、可能原因和下一步，不把“补一轮 stats”作为未经执行的可选建议。

详见 [`profiling/msys-analysis.md`](profiling/msys-analysis.md)。

#### `.mcu-rep`

1. 先按 [`mcu-report/reference/04-report-cli.md`](mcu-report/reference/04-report-cli.md) 保存并完整阅读 details，再导出 raw CSV。
2. 逐项检查五个分析维度，引用报告中实际存在的指标名、值、单位和 artifact 路径。Moore Perf Compute 不支持 `WarpStateStatistics`，不要做 instruction-level stall analysis。
3. 只有证据充分时才分类为 compute-bound、memory-bound、latency-bound 等；低吞吐率或单个固定阈值不能独立完成分类。
4. 若关键 section/metric 未采集，指出限制，并按 [`03-collection.md`](mcu-report/reference/03-collection.md) 给出最小补采方案；无法重新采集时停止在证据允许的结论上。

### D. 快速命令、版本与远程采集

- `msys` 快速使用：[`profiling/msys-usage.md`](profiling/msys-usage.md)
- MTTX 主机阶段插桩与采集：[`profiling/mttx-usage.md`](profiling/mttx-usage.md)
- `mcu` 采集、kernel 过滤、多次 launch、MPI/多进程、远程采集和版本相关选项：[`mcu-report/reference/03-collection.md`](mcu-report/reference/03-collection.md)
- 已有 `.mcu-rep` 的最短提取路径：[`mcu-report/reference/04-report-cli.md`](mcu-report/reference/04-report-cli.md)

快速回答只提供完成当前目的所需的最短路径，并提醒先用目标机的 `mcu --help`、`mcu --list-sections` 和实际 raw CSV 验证版本相关参数、section 与指标名。远程采集以远端环境为准，不假设 `/usr/local/musa/lib` 在所有机器存在。

---

# MUSA Kernel 深挖（PH1 / Moore Perf Compute）

**目标硬件（本仓库）：** PH1 架构。下面的大部分建议是通用的；与目标设备相关的细节必须从实际 Moore Perf Compute 报告和已安装工具链中核实。

## Golden rule

**Profile → Diagnose → Plan，按此顺序。绝不猜测。**

性能问题可能由一个主导瓶颈或多个相互作用的因素造成，采集时间也取决于 section、重放次数和 workload。在拿到报告之前不要编造假设；在把观察到的模式匹配到已知诊断之前不要开始写修复代码。不要罗列未经验证的建议——按证据强度、预期影响和验证成本排序。

---

## Quickstart（当有人说"profile 这个 kernel"时该做什么）

0. **先确认源码写入授权并创建新的运行目录。** “profile / 测试和优化 / 调优”默认不授权修改项目原始源码；没有明确授权时，将源码复制到仓库根目录 `profile/<run_name>/harness/` 或用户指定的实验目录后再迭代。一次运行一个目录，绝不复用已有目录。每次运行包含自己的 `harness/`、`reports/`、`analysis/` 和 `REPORT.md`。该规则在本仓库中为强制要求。见 [`mcu-report/reference/00-directory-layout.md`](mcu-report/reference/00-directory-layout.md)。

1. **确定要 profile 什么。** 输入是什么？走哪条 dispatch 路径？想回答什么问题？如果 kernel 的输入尺寸可变（变长 seq、变 batch size），必须从用户 workload 中挑选具体的代表性 shape——不要用任意输入做 profile。

2. **在隔离副本中构建独立的 harness**，除非用户是透过现有二进制做 profile。Harness 几秒内编译完成，可隔离运行 kernel，并让你控制输入和 launch 配置。源码和编译输出都放到 `profile/<run_name>/harness/` 或用户指定的实验目录；不得为了构建 harness 就地编辑项目原始源码。见 [`mcu-report/reference/02-harness-guide.md`](mcu-report/reference/02-harness-guide.md) 和 [`mcu-report/helpers/harness_template.cu`](mcu-report/helpers/harness_template.cu) 模板。

3. **跑一次 profile**：先用 `mcu --list-sections` 发现 section。即使列表包含 `WarpStateStatistics`，传给 `--sections` 前也必须删除它；不要采集或补采该 section。只有在需要更短迭代时才收窄 section 集合。输出写入 `profile/<run_name>/reports/`。见 [`mcu-report/reference/03-collection.md`](mcu-report/reference/03-collection.md)。

4. **用 Moore Perf Compute 的 CLI page 读取导入的报告。** 先 `mcu --import <report>.mcu-rep --page details` 获取 details 输出，再用 `mcu --import <report>.mcu-rep --page raw` 获取采集到的 metric 值。输出写入 `profile/<run_name>/analysis/`。见 [`mcu-report/reference/03-collection.md`](mcu-report/reference/03-collection.md) 和 [`mcu-report/reference/04-report-cli.md`](mcu-report/reference/04-report-cli.md)。

5. **走完五个分析维度。** 见 [`mcu-report/reference/05-analysis-dimensions.md`](mcu-report/reference/05-analysis-dimensions.md)。每个都重要，但对任何给定 kernel，通常只有 1–2 个占主导。Moore Perf Compute 不支持 `WarpStateStatistics`，跳过 instruction-level stall analysis。

6. **把模式匹配到诊断 playbook。** 见 [`mcu-report/reference/06-diagnosis-playbook.md`](mcu-report/reference/06-diagnosis-playbook.md)。它把 Moore Perf Compute 信号 → 可能原因 → 具体修复映射起来，并给出 "这个有多大" 的示例计数。

7. **写报告**，位于 `profile/<run_name>/REPORT.md`，给出有证据支撑、按预期影响排序的建议。见 [`mcu-report/reference/07-report-template.md`](mcu-report/reference/07-report-template.md)。

---

## 文件索引

### Reference docs（需要细节时阅读）

| 文件 | 用途 |
|---|---|
| [`mcu-report/reference/00-directory-layout.md`](mcu-report/reference/00-directory-layout.md) | **先读。** 目录 / 命名约定——一次运行 = 一个子目录，不允许交叉污染 |
| [`mcu-report/reference/01-workflow.md`](mcu-report/reference/01-workflow.md) | 从"用户请求"到"最终报告"的端到端检查清单 |
| [`mcu-report/reference/02-harness-guide.md`](mcu-report/reference/02-harness-guide.md) | 何时以及如何构建独立 harness（对 TVM-FFI、PyTorch kernel、JIT 编译代码为强制） |
| [`mcu-report/reference/03-collection.md`](mcu-report/reference/03-collection.md) | mcu 命令配方：section 发现、报告采集、多次 launch、MPI/多进程与远程采集 |
| [`mcu-report/reference/04-report-cli.md`](mcu-report/reference/04-report-cli.md) | 默认 CLI-first 报告提取，使用 `--page details` 和 `--page raw` |
| [`mcu-report/reference/05-analysis-dimensions.md`](mcu-report/reference/05-analysis-dimensions.md) | 五个分析维度：MP occupancy、balance、tensor core、timeline、memory。不含 instruction-level stall analysis |
| [`mcu-report/reference/06-diagnosis-playbook.md`](mcu-report/reference/06-diagnosis-playbook.md) | 使用 Moore Perf Compute 信号的 pattern → diagnosis → fix |
| [`mcu-report/reference/07-report-template.md`](mcu-report/reference/07-report-template.md) | 如何组织最终报告 |
| [`mcu-report/reference/08-metric-names.md`](mcu-report/reference/08-metric-names.md) | 候选 metric 名称——可用性必须在目标设备上验证 |
| [`mcu-report/reference/09-common-issues.md`](mcu-report/reference/09-common-issues.md) | 权限、PM sampling gap、TVM-FFI / PyTorch 注意事项 |

### Helpers（可复用代码）

| 文件 | 用途 |
|---|---|
| [`mcu-report/helpers/harness_template.cu`](mcu-report/helpers/harness_template.cu) | 独立 harness 模板——把你的 kernel 贴进去，填好输入分配，完成 |
| [`mcu-report/helpers/safetensors_loader.h`](mcu-report/helpers/safetensors_loader.h) | header-only safetensors 读取器（无外部依赖），用于加载真实 workload 张量 |
| [`mcu-report/helpers/analyze_reports.py`](mcu-report/helpers/analyze_reports.py) | details/raw 提取、关键 metric 与比较的 CLI wrapper |
| [`mcu-report/helpers/list_flashinfer_workloads.py`](mcu-report/helpers/list_flashinfer_workloads.py) | 浏览 flashinfer-trace 数据集——shape 直方图、按轴过滤、为特定 UUID 解析 safetensors 路径 |

---

## Critical lessons（不要跳过）

1. **Metric 名称依赖设备与版本。** 从 `mcu --import <report>.mcu-rep --page raw --csv` 读取 metric 名称和值；[`mcu-report/reference/08-metric-names.md`](mcu-report/reference/08-metric-names.md) 中的名称只是搜索提示。

2. **Tail effects 需要来自实际报告的证据。** 先用 details page 和 raw CSV metadata（`Grid Size`、`Block Size`、kernel duration、active cycles）。只有当导入的报告确实包含 per-instance 数据时才使用 per-instance 数据。

3. **变长输入上的 load-imbalance 常常是 #1 瓶颈。** 如果用户 workload 的序列长度不一，per-MP active-cycle 方差往往会盖过其他所有效应。始终检查输入分布。

4. **在提取 raw metric 之前先读完完整的 details 输出。** 把它提供的任何诊断文本作为上下文，再用 raw CSV 中的值支撑诊断。

5. **不要委托理解。** 自己跑 profile、自己打开报告、引用具体 metric 值。绝不要写"profile 显示它是 memory-bound"——而要给出支撑结论的两三个 metric 值（例如 "`dram_throughput.avg.pct_of_peak_sustained_elapsed` 很低，同时 `mp_throughput.avg.pct_of_peak_sustained_elapsed` 也很低，说明 kernel 是利用率不足，而不是 DRAM 带宽受限"）。填入报告中的实际数字。具体性就是交付物。

---

## Related skills

- [`mcu-report/ph1-musa-programming.md`](mcu-report/ph1-musa-programming.md) — PH1 MUSA 编程参考。
