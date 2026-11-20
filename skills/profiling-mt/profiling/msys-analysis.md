# Moore Perf System 报告分析指南

本文介绍如何分析 Moore Perf System 生成的 `.msys-rep` 报告文件。命令行工具是 `msys`，图形界面是 `msys-ui`。

---

## 快速开始

### 使用自动分析脚本（推荐）

```bash
# 自动检测报告类型，先看 GPU gap，再继续做 stats 深挖
python3 scripts/analyze_msys_report.py report.msys-rep
```

脚本会自动：
1. 检测报告类型（OpenGL / MUSA Compute / MUSA API）
2. 分析 GPU gap / timeline 连续性
3. 继续做 stats 汇总，提炼 top3 热点数据（API 和 GPU Kernel）
4. 提供优化建议

**输出示例：**
```
======================================================================
Moore Perf System 报告分析
======================================================================
正在检测报告类型...
  报告类型：MUSA Compute (包含 GPU Kernel 数据)

======================================================================
MUSA GPU Kernel 分析
======================================================================

Top 3 GPU Kernels (按总执行时间):
----------------------------------------------------------------------

  #1: void mul_mat_vec_q<...>
      总执行时间：848.64 ms (33.13%)
      调用次数：11128
      平均时间：0.076 ms
      建议：该 kernel 占总时间 33.1%，是主要优化目标
...
```

---

## 报告类型检测

Moore Perf System 报告分为三种类型，检测方法如下：

### 检测 OpenGL 报告
```bash
msys stats -f json -o <output> -r opengl_api_sum <report.msys-rep>
```
如果输出文件有内容，则为 OpenGL 报告。

### 检测 MUSA Compute 报告
```bash
msys stats -f json -o <output> -r musa_gpu_kern_sum <report.msys-rep>
```
如果输出文件有内容，则为 MUSA Compute 报告。

### 检测 MUSA API 报告
```bash
msys stats -f json -o <output> -r musa_api_sum <report.msys-rep>
```
如果输出文件有内容，则为 MUSA API 报告。

---

## 使用自动分析脚本

### 基本用法

```bash
python3 scripts/analyze_msys_report.py report.msys-rep
```

### 指定输出目录

```bash
python3 scripts/analyze_msys_report.py report.msys-rep ./output
```

### 输出示例

```
======================================================================
Moore Perf System 报告分析
报告文件：report.msys-rep
======================================================================

正在检测报告类型...
  报告类型：MUSA Compute

======================================================================
MUSA Compute 报告分析
======================================================================

Top 3 GPU Kernels:
----------------------------------------------------------------------

  #1: matrix_multiply_kernel
      执行时间：15.234 ms
      数据传输：256.00 MB
      带宽：512.5 GB/s
      建议：该 kernel 执行时间较长，考虑优化

  #2: conv2d_forward
      执行时间：8.567 ms
      数据传输：128.00 MB
      建议：该 kernel 执行时间较长，考虑优化

  #3: softmax_kernel
      执行时间：3.123 ms
      数据传输：32.00 MB

======================================================================

详细数据已导出至：/tmp/msys_analysis_xxx/musa_gpu_kern_sum.json
使用以下命令在 GUI 中查看:
  msys-ui report.msys-rep
```

### 用户问 top kernel 时的标准回答

当用户明确在问“top kernel 是谁 / 最耗时 kernel 是谁 / 哪个 kernel 最热”时，优先按下面格式直接回答，不要只给 kernel 名称。

**标准输出模板：**
```text
Top kernel 是 <kernel_name>。
- 总执行时间：<total_time>
- 占比：<percentage>
- 调用次数：<instances>
- 平均时间：<avg_time>
- 结论：<一句判断或建议>
```

**示例（report_llama.msys-rep）：**
```text
Top kernel 是 void mul_mat_vec_q<...>。
- 总执行时间：848.64 ms
- 占比：33.13%
- 调用次数：11128
- 平均时间：0.076 ms
- 结论：该 kernel 占总时间约三分之一，是当前最优先的优化目标。
```

如果用户继续追问，再补充第二、第三名以及是否建议转到 `mcu` 深挖。

---

## CLI 分析方法

### 1. 导出为 Chrome Tracing 格式

```bash
msys export -t json report.msys-rep
```

导出的 JSON 文件可在 Chrome 浏览器中打开 (`chrome://tracing/`)，便于分享和查看时间线。

---

### 2. 生成统计报告

```bash
# 查看可用报告类型
msys stats --help

# 生成汇总报告（输出到控制台）
msys stats report.msys-rep

# 输出到文件（CSV 格式）
msys stats -f csv -o output report.msys-rep

# 指定报告类型
msys stats -r musa_api_sum,musa_gpu_kern_sum report.msys-rep
```

**常用报告类型：**

| 报告类型 | 说明 | 适用 |
|---------|------|------|
| `opengl_api_sum` | OpenGL API 调用汇总 | OpenGL 报告 |
| `musa_api_sum` | MUSA API 调用汇总 | MUSA API 报告 |
| `musa_gpu_kern_sum` | GPU kernel 汇总 | MUSA Compute 报告 |
| `musa_gpu_kern_gb_sum` | GPU kernel 数据传输汇总 | MUSA Compute 报告 |
| `musa_gpu_sum` | GPU 汇总统计 | MUSA 报告 |

---

### 3. 自动优化分析

```bash
# 运行所有分析规则
msys analyze report.msys-rep

# 指定分析规则
msys analyze --rule=musa_memcpy_async,musa_gpu_gaps report.msys-rep

# 查看所有可用规则
msys analyze --help-rules ALL

# 查看特定规则说明
msys analyze --help-rules musa_gpu_gaps
```

**可用分析规则：**

| 规则 | 说明 |
|------|------|
| `musa_memcpy_async` | 检测可异步化的内存拷贝 |
| `musa_memcpy_sync` | 检测同步内存拷贝问题 |
| `musa_memset_sync` | 检测 memset 同步问题 |
| `musa_api_sync` | 检测 API 同步问题 |
| `musa_gpu_gaps` | 检测 GPU 空闲时段 |
| `musa_gpu_time_util` | GPU 时间利用率分析 |

---

## GUI 分析方法

### 打开报告

1. 启动 Moore Perf System GUI (`msys-ui`)
2. 文件 → 打开报告 → 选择 `.msys-rep` 文件

> **提示**: 大型报告（超过 3000000 个事件）需要选择时间范围加载。

---

### 主要视图

#### 1. 时间线视图 (Timeline)

**布局：**
- 左侧树状结构：进程/线程/API 调用层次
- 右侧图表：时间线上的事件分布

**功能：**
- 缩放：滑块调整垂直高度，放大镜重置
- 滚动：鼠标滚轮或拖动时间轴
- 标记事件：右键点击事件 → 标记
- 在事件视图中显示：右键行 → 在事件视图中显示

---

#### 2. 事件视图 (Events View)

**功能：**
- 表格形式显示追踪事件
- 支持搜索、排序、过滤
- 多选：使用 Shift 或 Ctrl

**右键菜单：**
- 在时间线上缩放到选定项
- 标记事件
- 清除选定事件
- 清除过滤事件

---

#### 3. 统计视图 (Statistics)

显示内容：
- GPU 使用情况统计
- 带宽利用率
- API 调用统计
- 内存操作统计

---

#### 4. 专家视图 (Expert View)

显示内容：
- 自动识别的性能问题
- 优化建议
- 瓶颈分析

---

## 关键指标解读

### GPU 利用率指标

| 指标 | 含义 | 理想值 | 问题诊断 |
|------|------|--------|---------|
| SM Occupancy | SM 资源利用率 | >70% | 低则检查 block size、寄存器使用 |
| GPU Utilization | GPU 活跃时间占比 | >80% | 低则检查 CPU-GPU 同步 |
| Memory Bandwidth Util | 内存带宽利用率 | 视应用而定 | 过高可能是瓶颈 |

---

### 常见问题识别

| 问题 | 现象 | 可能原因 | 优化方向 |
|------|------|---------|---------|
| **GPU Gaps** | GPU 空闲时段过长 | CPU-GPU 同步问题 | 减少同步点、异步化 |
| **Low Occupancy** | SM 利用率低 | block size 过小、寄存器过多 | 调整 block size、减少寄存器 |
| **Sync Memcpy** | 同步内存拷贝 | 使用了同步 memcpy | 改为异步 memcpy |
| **Low Bandwidth Util** | 内存带宽利用率低 | 非合并访问 | 优化内存访问模式 |

---

## 分析流程

### 第一步：检测报告类型
```bash
python3 scripts/analyze_msys_report.py report.msys-rep
```

### 第二步：查看 top3 热点
脚本自动输出 top3 数据

### 第三步：瓶颈分析
1. 查看 GPU 利用率指标
2. 检查 GPU gaps
3. 分析内存操作

### 第四步：优化建议
1. 参考脚本输出的优化建议
2. 查看专家视图的自动分析结果
3. 制定优化方案并验证

---

## 常见问题

### Q: 报告文件太大打不开？
- 使用时间范围选择功能，只加载部分数据
- 使用 CLI 导出为 JSON 后用其他工具分析
- 使用 `msys stats` 生成汇总报告代替完整分析

### Q: 如何对比两次运行的结果？
- GUI: 打开两个窗口并排对比
- CLI: 导出为 CSV 后用脚本对比
```bash
msys stats -f csv -o run1 report1.msys-rep
msys stats -f csv -o run2 report2.msys-rep
```

### Q: 如何定位性能回归？
1. 保存基线报告
2. 使用相同配置重新分析
3. 对比关键指标变化（GPU 利用率、API 调用次数等）

### Q: 如何分析特定时间段？
- GUI: 使用时间范围选择功能
- CLI: 导出后过滤特定时间范围的事件

---

## 脚本说明

**analyze_msys_report.py** 参数：

| 参数 | 说明 |
|------|------|
| `report.msys-rep` | Moore Perf System 报告文件路径（必填） |
| `output_dir` | 输出目录（可选，默认临时目录） |

**输出内容：**
- 报告类型
- Top3 热点数据
- 优化建议
- 详细 JSON 数据文件位置

---

## 相关文档

- [msys-usage.md](msys-usage.md) - Moore Perf System 使用指南
- [scripts/analyze_msys_report.py](scripts/analyze_msys_report.py) - 自动分析脚本
