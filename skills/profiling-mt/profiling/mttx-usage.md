# MTTX 使用指南

MTTX（Moore Threads Tools Extension）用于在应用源码中添加标记（marker）和区间（range），把主机侧业务语义传递给 Moore Perf System。MTTX 本身不生成报告；必须由支持 MTTX 的 `msys` 采集并在时间线中查看。

本文已包含 profiling 流程所需的 MTTX 1.0.0 核心用法，不要求读取技能目录之外的说明文档。

## Profiling 工作流中的使用原则

当性能问题涉及 CPU 生成、预处理、后处理、内存初始化/释放、锁页内存访问、主机调度或 GPU gap 时，应在**隔离实验副本**中主动添加 MTTX 区间，并用 `musa,osrt,mttx` 联合采集：

```bash
msys profile --trace=musa,osrt,mttx --osrt-threshold=1000 \
  -e LD_LIBRARY_PATH=/usr/local/musa/lib -o cpu_ranges ./app
```

执行要求：

1. 标注优化前后的相同阶段，保持范围名称、workload 和采集窗口一致。
2. MTTX 区间测得的是主机线程上的**经过时间（elapsed time）**，不是纯 CPU on-core 时间。范围内的 MUSA 同步、锁等待、I/O 和 sleep 都会计入。
3. 必须结合 OSRT、MUSA API、kernel 和 MemOps 时间线解释区间；不要用 H2D/D2H 或 MUSA API 时间代替 CPU 阶段时间。
4. 插桩只进入实验副本或候选 patch。没有源码写入授权时，不修改原始项目。
5. 另用无 profiler 的重复运行测端到端时间，避免把 MTTX 和 tracing 开销误判为应用性能变化。

## 环境检查

MTTX 1.0.0 要求 Moore Perf System 1.9.0 或更高版本。实际参数始终以目标机为准：

```bash
msys --version
msys profile --help
```

确认帮助中支持 `mttx` trace；若使用捕获范围，还要确认 `--capture-range=mttx` 和 `--mttx-capture`。

### C/C++

公开头文件为：

```text
mttx/mtToolsExt.h   # C API
mttx/mttx.hpp       # C++ API
```

使用 MUSA Toolkit 时可检查：

```bash
export MTTX_INCLUDE_DIR=/usr/local/musa/include
test -f "$MTTX_INCLUDE_DIR/mttx/mtToolsExt.h"
test -f "$MTTX_INCLUDE_DIR/mttx/mttx.hpp"
```

POSIX 系统使用普通 C/C++ 编译器时，最终链接命令需要 `-ldl`：

```bash
cc  -I"$MTTX_INCLUDE_DIR" app.c   -ldl -o app
c++ -std=c++11 -I"$MTTX_INCLUDE_DIR" app.cpp -ldl -o app
```

若使用 `mcc`，也应先以目标工具链进行最小编译和运行验证，不假定所有版本的链接行为相同。

### Python

```bash
python -m pip install mttx
python -c 'import mttx; mttx.mark("import check")'
```

若默认软件源不提供 `mttx`，应使用目标实验环境已配置的软件源或预装包；本技能不依赖固定的外部下载地址。MTTX 1.0.0 的预编译 wheel 通常要求 Linux x86_64 与 Python 3.10；其他环境可能需要目标项目自行提供兼容包。

## 标注模型

| 类型 | 含义 | 适用场景 |
|---|---|---|
| Marker | 瞬时事件 | 请求进入、cache miss、重试、状态切换 |
| Push/Pop range | 同一线程、同一域中的栈式区间 | 函数、嵌套阶段、词法代码块 |
| Start/End range | 通过 ID 配对，可跨线程或相互重叠 | 异步任务、对象生命周期 |
| Domain | 隔离组件的标注、类别和字符串 | 库、子系统、应用模块 |
| Category | 在域内稳定分组 | I/O、计算、同步、分配 |
| Payload | 关联数值，仅 C/C++ 支持 | batch size、元素数量等动态值 |

自然嵌套的工作优先 Push/Pop；只有生命周期无法用栈表达时才使用 Start/End。

## C++ 用法

C++ 对嵌套工作优先使用 RAII，确保异常和提前返回时区间自动闭合：

```cpp
#include <mttx/mttx.hpp>

void cpu_generate(...) {
  mttx::scoped_range range{"cpu_generate"};
  // CPU work
}

void process_batch(...) {
  MTTX_FUNC_RANGE();

  {
    mttx::scoped_range range{"host_init"};
    // initialize host buffers
  }
  {
    mttx::scoped_range range{"checksum"};
    // CPU post-processing
  }
}
```

瞬时事件使用 marker：

```cpp
mttx::mark("application started");
```

生命周期跨越词法作用域时才使用 `mttx::unique_range`，其 Start/End 模型开销高于 `scoped_range`。

## C 用法

```c
#include <mttx/mtToolsExt.h>

mttxMarkA("application started");
mttxRangePushA("cpu_generate");
/* CPU work */
mttxRangePop();
```

Push/Pop 必须在同一线程和同一域中执行，并保证错误、提前返回等所有路径都执行 Pop。若工作可跨线程，使用 Start/End：

```c
mttxRangeId_t id = mttxRangeStartA("asynchronous request");
/* May complete on another thread. */
mttxRangeEnd(id);
```

每个 ID 只能结束一次；关联 domain 必须存活到 End。

## Python 用法

优先使用装饰器或上下文管理器：

```python
import mttx

@mttx.annotate(color="blue", domain="com.example.pipeline")
def cpu_generate():
    pass

with mttx.annotate("checksum", category="postprocess"):
    checksum()

mttx.mark("batch completed")
```

手动 Push/Pop 时使用 `try/finally`：

```python
mttx.push_range("request")
try:
    handle_request()
finally:
    mttx.pop_range()
```

Python 当前不支持 payload。

## Profiling 阶段划分建议

按性能问题选择阶段，不要机械标注每个函数。CPU/GPU 管线通常优先覆盖：

```text
application / batch / iteration
├── host_alloc
├── host_init
├── cpu_generate
├── preprocess
├── submit_or_copy
├── postprocess
├── checksum
└── host_free
```

建议：

- 使用稳定、明确的操作名称；避免 `work`、`step` 等模糊名称。
- 范围边界应匹配真实工作单元。
- 不要在每个元素或极短循环中插入范围。
- 动态数值优先用 C/C++ payload，不要生成大量高基数字符串。
- 高频重复消息优先使用 registered string，以降低性能损失。
- 可复用库或主要子系统使用稳定 domain；不要为每个请求创建 domain。
- 类别 ID 在同一 domain 中只能命名一次，并应跨版本保持稳定。

## 采集、捕获和验证

### 常规联合采集

```bash
msys profile --trace=musa,osrt,mttx --osrt-threshold=1000 \
  -e LD_LIBRARY_PATH=/usr/local/musa/lib -o report ./app
```

### 只验证 MTTX 链路

```bash
msys profile --trace=mttx -o mttx_check ./app
```

### 只捕获指定 MTTX 范围

参数名称以目标机 `msys profile --help` 为准。支持时可使用：

```bash
msys profile --trace=musa,osrt,mttx \
  --capture-range=mttx --mttx-capture='process_batch' \
  -o selected_range ./app
```

若使用自定义 domain，按帮助中的 `range@domain` 形式指定。`--capture-range=mttx` 必须同时启用 `--trace=mttx`。

### 查看结果

优先在 Moore Perf System GUI 时间线中：

1. 找到 MTTX 行或标注分组。
2. 搜索稳定消息，例如 `cpu_generate`。
3. 检查嵌套顺序、持续时间、线程、domain 和 category。
4. 对齐同时间段的 OSRT、MUSA API、kernel 和 MemOps。
5. 区分 CPU 工作、阻塞等待、同步等待和 GPU 执行。

也可导出时间线：

```bash
msys export -t json report.msys-rep
```

不同 `msys` 版本未必提供 MTTX/OSRT 的 `msys stats` 报告类型。不得猜测报告名；先检查当前版本帮助。没有 stats 支持时，使用 GUI 或导出时间线并明确限制。

## 开销控制与对照实验

- 先用短且有代表性的 workload 验证标注链路。
- 插桩粒度以阶段为主，不标注微小 helper 或每次元素访问。
- 对每个候选分别保留：无 profiler 端到端测试、带 MTTX/OSRT 的诊断采集。
- 若报告过大，缩短 duration、提高 OSRT threshold 或用 MTTX capture range；不要首先删除关键阶段标注。
- 分别验证接入和未接入采集工具时应用行为一致。
- 如需无标注构建，在包含 MTTX 头文件前定义 `MTTX_DISABLE`：

```bash
c++ -DMTTX_DISABLE -I"$MTTX_INCLUDE_DIR" app.cpp -ldl -o app-no-mttx
```

## 常见问题

### 报告没有 MTTX 事件

依次检查：

1. 添加标注后是否重新构建。
2. 是否误定义 `MTTX_DISABLE`。
3. `msys profile --help` 是否支持 `mttx`。
4. 采集命令是否包含 `--trace=mttx`。
5. 是否打开了正确的 `.msys-rep`。
6. 用最小示例和 `application started` marker 验证链路。

直接运行应用没有 MTTX 控制台输出是正常现象；MTTX 只向接入的工具传递标注。

### 区间错误或未结束

- Push 与 Pop 必须位于同一线程、同一 domain。
- 按后进先出顺序结束嵌套区间。
- 所有错误和提前返回路径都必须清理。
- Start/End 必须使用准确 ID，且每个范围只 End 一次。
- C++ 优先改用 `mttx::scoped_range`。

### 编译或链接失败

- `-I` 应指向直接包含 `mttx/` 的目录，而不是 `mttx/` 本身。
- C 包含 `<mttx/mtToolsExt.h>`，C++ 包含 `<mttx/mttx.hpp>`。
- POSIX 最终链接命令添加 `-ldl`。

## 交付要求

使用 MTTX 完成 CPU 阶段分析后，结果至少记录：

- 插桩文件与范围名称；
- 构建命令、应用参数和 workload；
- `msys`/MTTX 版本与采集命令；
- 各阶段 elapsed time，以及其中的 OSRT/MUSA 同步或等待证据；
- 未插桩、无 profiler 的端到端 before/after；
- `.msys-rep`、导出时间线和候选 patch 路径；
- MTTX elapsed time 与纯 CPU on-core time 的证据边界。
