# MUSA FFN Profiling Demo

这个 demo 用 MUSA 模拟 Transformer 中一个 Feed-Forward Network（FFN）层的推理过程，用来演示如何使用 `msys` 和 `mcu` 定位并优化 GPU kernel。

它不是一个孤立的 kernel，而是一个包含多个 kernel 的完整 MUSA 程序：输入填充、两次矩阵乘法、bias add、GELU、ReLU、row sum 和 layer norm。程序的主要热点是第二次矩阵乘法 `matmul_w2`。

## 1. msys 和 mcu 的分工

可以把两个工具理解为两个分析层次：

- `msys` 面向完整程序：记录 CPU/API/GPU 活动，回答“整个程序最耗时的 kernel 是谁”。
- `mcu` 面向单个 kernel：采集计算管线、访存、warp 调度、shared memory 等硬件指标，回答“这个 kernel 为什么慢，以及下一步应该改什么”。

推荐流程是：

```text
完整程序
  → msys 找到热点 kernel
  → mcu 深入分析热点 kernel
  → 修改一个主要因素
  → 重新运行并重新 profile
  → 根据 before/after 数据决定下一步
```

## 2. Demo 工作负载

矩阵规模如下：

```text
M  = 4096
K1 = 512
H  = 2048
K2 = 2048
N  = 1024
```

主要计算流程：

```text
X
 → matmul_w1
 → bias add
 → GELU
 → matmul_w2       ← 主要优化目标
 → bias add
 → ReLU
 → row sum
 → layer norm
 → Y
```

## 3. 编译 Demo

以下命令在服务器上的 MUSA 工具链环境中执行。源码文件为 `musa_ffn_demo.mu`，通过编译宏 `FFN_W2_VERSION` 选择不同版本的 `matmul_w2` kernel。

```bash
mcc -std=c++17 -O2 -mtgpu \
    --cuda-gpu-arch=mp_31 \
    -DFFN_W2_VERSION=<version> \
    -o musa_ffn_demo \
    musa_ffn_demo.mu -lmusart
```

通过编译宏 `FFN_W2_VERSION` 选择 v1～v4：

```bash
-DFFN_W2_VERSION=1
-DFFN_W2_VERSION=2
-DFFN_W2_VERSION=3
-DFFN_W2_VERSION=4
```

## 4. MCU 采集配置

本 demo 的 MCU 报告统一使用以下 section，保证每个版本的数据可以横向比较：

```text
SpeedOfLight,
ComputeWorkloadAnalysis,
MemoryWorkloadAnalysis,
MemoryWorkloadAnalysis_Chart,
MemoryWorkloadAnalysis_Tables,
SchedulerStats,
InstructionStats,
LaunchStats
```

示例命令：

```bash
mcu -f \
  --sampling-buffer-size 4194304 \
  -k <kernel-name> \
  -c 1 \
  --sections SpeedOfLight,ComputeWorkloadAnalysis,MemoryWorkloadAnalysis,MemoryWorkloadAnalysis_Chart,MemoryWorkloadAnalysis_Tables,SchedulerStats,InstructionStats,LaunchStats \
  -o <report-name>.mcu-rep \
  ./musa_ffn_demo_v
```

其中：

- `-k` 只分析目标 kernel，避免其他 kernel 干扰；
- `-c 1` 只采集一个匹配的 kernel launch；
- `MemoryWorkloadAnalysis_Tables` 包含 shared-memory bank conflict 等访存细节；
- `SchedulerStats` 用于分析 Active Warps、Eligible Warps 和调度等待；
- `ComputeWorkloadAnalysis` 用于观察计算管线和计算吞吐。

导出报告：

```bash
mcu --import <report-name>.mcu-rep --page details > analysis/details_<name>.txt
mcu --import <report-name>.mcu-rep --page raw --csv -f -o analysis/raw_<name>.csv
```

## 5. 优化过程：V1 → V4

每一轮优化遵循同一个闭环：

```text
采集数据 → 确定优化方向 → 只修改一个主要因素
→ 重新采集 → 对比数据 → 决定下一步或停止
```

### V1：建立 baseline

配置：

```text
block = (8, 8, 1)       = 64 threads = 2 warps
grid  = (128, 512, 1)   = 65,536 blocks
每个线程计算 1 个输出
```

#### 采集数据

首先使用 msys 分析完整 FFN 程序。v1 的 GPU kernel 汇总显示：

```text
matmul_w2_kernel_baseline   34.34 ms
占 GPU kernel 时间          78.64%
```

因此确认 `matmul_w2` 是完整程序的主要热点，再使用 mcu 分析它：

```text
Compute(MP) Throughput       26.27%
Memory Throughput              1.43%
DRAM Throughput                0.06%
Eligible Warps/Scheduler       0.81
Shared Memory Bank Conflicts      0
```

#### 确定优化方向

DRAM throughput 很低，说明问题不是显存带宽已经打满；Compute Throughput 较低，同时一个 block 只有 2 个 warp，Eligible Warps 也较低。因此优先怀疑 block 配置过小，导致并行度和调度隐藏延迟的能力不足。

#### 优化

只改变 launch 配置：将 block 从 `8×8` 增大到 `16×16`，每线程计算量和 shared-memory tile 逻辑保持不变。

#### 下一步

V1 是基线，不做 before/after 判断。下一步进入 V2，验证增大 block 是否改善计算利用率。

### V2：增大 block size

配置：

```text
block = (16, 16, 1)     = 256 threads = 8 warps
grid  = (64, 256, 1)    = 16,384 blocks
每个线程计算 1 个输出
```

#### 采集数据并判断

与 V1 对比：

```text
指标                         V1          V2
matmul_w2 duration           34.37 ms    17.52 ms
Compute(MP) Throughput       26.27%      29.64%
Eligible Warps/Scheduler      0.81        1.56
Shared Memory Bank Conflicts     0           0
```

duration 减少约一半，Eligible Warps 增加，Compute Throughput 也提升，说明增大 block 后，MP 上有更多可调度的 warp，计算资源利用率改善。

#### 下一步方向

V2 的 block 配置已经优于 V1，但每个线程仍只计算一个输出。此时可以尝试增加线程级工作量和数据复用，让加载到寄存器或 shared memory 的数据支持更多乘加操作。

### V3：增加每线程计算量

配置：

```text
block = (16, 16, 1)     = 256 threads = 8 warps
grid  = (32, 256, 1)    = 8,192 blocks
每个线程计算 2 个相邻输出
```

#### 采集数据并判断

相对 V2，只改变每线程计算量：

```text
指标                         V2          V3
matmul_w2 duration           17.52 ms     9.96 ms
Compute(MP) Throughput       29.64%      39.40%
Memory Throughput              1.84%       1.84%
Shared Memory Bank Conflicts     0      16,777,230
```

duration 和 Compute Throughput 都明显改善，说明线程级数据复用有效。但 V3 的 B tile 扩展为 `16×32`，shared-memory 行跨度为 32 个 float。一个 warp 覆盖两行线程时，两行数据映射到重叠的 bank，于是出现大量 bank conflict。

这里的结论不是“V3 失败”，而是：计算映射优化成功，同时暴露出了新的 memory-side 瓶颈。下一步应只修复这个 shared-memory 布局问题。

### V4：优化 shared-memory 访问

V4 保持 V3 的 block、grid 和每线程双输出不变，只将 B tile 从：

```text
V3: bs[16][32]
V4: bs[16][33]
```

增加一列 padding，改变每行数据到 shared-memory bank 的映射。

#### 采集数据并判断

```text
指标                         V3          V4
matmul_w2 duration            9.96 ms     9.95 ms
Compute(MP) Throughput       39.40%      39.75%
Memory Throughput              1.84%       1.86%
Shared Memory Bank Conflicts 16,777,230       0
```

V4 消除了 bank conflict，Compute Throughput 和 Memory Throughput 小幅提升，kernel duration 继续下降。此时四个版本形成了没有性能回退的优化链路：

```text
V1  34.37 ms
 ↓ 增大 block
V2  17.52 ms
 ↓ 增加每线程计算量
V3   9.96 ms
 ↓ padding 优化 shared-memory 访问
V4   9.95 ms
```

## 6. 如何阅读关键 MCU 数据

- **Compute(MP) Throughput**：计算管线利用率。较低时，可以检查 block 配置、warp 并行度、线程级工作量和数据复用。
- **Memory Throughput / DRAM Throughput**：分别观察 GPU memory 子系统和 DRAM 的利用率。DRAM 低不代表没有 shared-memory 问题。
- **Active Warps**：当前驻留在 MP 上的 warp 数量，用于观察并行度。
- **Eligible Warps**：当前可以立即发射指令的 warp 数量。Active Warps 高但 Eligible Warps 低，通常说明 warp 在等待数据、同步或指令依赖。
- **Shared Memory Bank Conflicts**：多个线程访问同一 shared-memory bank 的情况。该值升高时，应检查 tile 的行跨度、转置布局和线程访问模式。
- **Pipe Utilization**：观察 PVA、LSU、SFU 等硬件管线的忙碌程度，帮助判断计算、访存或特殊函数是否更突出。

任何单个指标都不能独立证明瓶颈。应固定输入规模、GPU、编译选项和 profiling section，同时比较 kernel duration、吞吐率、调度指标和访存指标。
