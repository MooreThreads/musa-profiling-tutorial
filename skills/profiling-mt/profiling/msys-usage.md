# Moore Perf System 使用指南

Moore Perf System 是系统级性能分析工具，用于 API 追踪和 GPU 指标采集。命令行工具是 `msys`，图形界面是 `msys-ui`。

> **默认采集要求：** 分析完整 MUSA 程序时，除非工具版本不支持、开销不可接受或任务明确只关注 GPU，必须使用 `--trace=musa,osrt,mttx`，主动采集 OS Runtime 与 MTTX。不得仅用 `--trace=musa` 后声称已分析 CPU 时间。若关闭 `osrt` 或 `mttx`，需在结果中记录原因和证据边界。

## 快速开始

### 基本用法
```bash
# 完整程序的默认配置：同时采集 MUSA、OS Runtime 和 MTTX
msys profile --trace=musa,osrt,mttx --osrt-threshold=1000 \
  -e LD_LIBRARY_PATH=/usr/local/musa/lib -o report <application> [<app args>]

# 仅在明确不需要 CPU/主机侧证据时，才收窄 trace
msys profile --trace=musa -o gpu_only <application> [<app args>]
```

`--osrt-threshold=1000` 仅记录耗时至少 1 μs 的 OS Runtime 调用，以控制采集开销和报告大小。阈值必须结合目标机 `msys profile --help` 核实；降低阈值前先做短采集。

### 常用命令

#### 1. 限制追踪类型和时长
```bash
msys profile --duration=10 --trace=musa,osrt,mttx --osrt-threshold=1000 \
  -e LD_LIBRARY_PATH=/usr/local/musa/lib -o musa_test <application>
```
- `--duration=10`: 捕获 10 秒
- `--trace=musa,osrt,mttx`: 同时追踪 MUSA API、OS Runtime 与用户标注范围
- `--osrt-threshold=1000`: 忽略短于 1 μs 的 OS Runtime 调用，避免报告过大
- `-e`: 设置环境变量
- `-o musa_test`: 输出文件名为 musa_test.msys-rep

#### 2. 延迟启动捕获
```bash
msys profile -y 10 --trace=opengl -o opengl_test <application>
```
- `-y 10`: 延迟 10 秒后开始捕获

#### 3. 指定 GPU 设备
```bash
msys profile -d 0,1 <application>
```
- `-d 0,1`: 只分析 GPU 0 和 1

#### 4. 采集 GPU 指标
```bash
msys profile --gpu-metrics-set=all <application>
```

#### 5. 交互式控制
```bash
# 创建会话
msys start

# 启动应用
msys launch <application>

# 开始收集
msys start

# 停止收集
msys stop

# 或取消并退出
msys cancel -q
```

#### 6. 查看会话
```bash
msys sessions list
```

#### 7. 主动采集 OSRT 与 CPU 主机阶段

完整程序 profiling 默认启用：

```bash
msys profile --trace=musa,osrt,mttx --osrt-threshold=1000 \
  -e LD_LIBRARY_PATH=/usr/local/musa/lib -o full_trace ./app
```

执行要求：

1. 先运行目标机的 `msys profile --help`，确认支持 `osrt`、`mttx` 和 `--osrt-threshold`；参数以目标机版本为准。
2. `osrt` 用于观察线程的 OS Runtime 调用、阻塞、等待、同步等时间线证据。它不等价于 CPU 硬件计数器或完整采样 profiler；不能仅凭 OSRT 推断 CPU 指令、cache miss 或函数级 CPU 利用率。
3. 优先在 GUI 时间线或 `msys export -t json` 导出的 trace 中联合检查 OSRT、MTTX、MUSA API、kernel 和 MemOps。当前版本若没有 OSRT/MTTX 的 `msys stats` 报告类型，不得编造报告名；使用时间线/导出结果并说明限制。
4. 若报告过大，先提高 `--osrt-threshold`，或缩短 `--duration`/使用 capture range；不要直接关闭 OSRT。必须关闭时记录原因。
5. 每轮优化采用相同 trace 集、OSRT 阈值、workload 和采集窗口；另用无 profiler 的重复运行测端到端时间，避免把 tracing 开销当成应用退化。

#### 8. 需要 CPU 阶段时间时插入 MTTX

当问题涉及 CPU 生成、预处理、后处理、内存初始化/释放、锁页内存访问或主机侧调度时，应在**隔离实验副本**中主动添加 MTTX 区间，再用 `--trace=musa,osrt,mttx` 采集。不要仅以 H2D/D2H 或 MUSA API 时间代替 CPU 阶段时间。

MTTX 的环境检查、C/C++/Python 插桩、区间模型、capture range、开销控制和故障排查统一见 [`mttx-usage.md`](mttx-usage.md)。MTTX 区间是 elapsed time，不是纯 CPU on-core time；分析时必须与 OSRT 和 MUSA 时间线对齐。

## 报告处理

### 导出为 Chrome Tracing 格式
```bash
msys export -t json report.msys-rep
```
导出的 json 文件可在 Chrome 浏览器中打开 (chrome://tracing/)

### 生成统计报告
```bash
# 输出到控制台
msys stats report.msys-rep

# 输出到文件
msys stats -o output_basename report.msys-rep

# 指定格式 (table/csv/json)
msys stats -f csv report.msys-rep

# 指定报告类型
msys stats -r musa_api_sum,musa_gpu_kern_sum report.msys-rep
```

**常用报告类型：**
- `musa_api_sum` - MUSA API 调用汇总
- `musa_api_trace` - MUSA API 追踪
- `musa_gpu_kern_sum` - GPU kernel 汇总
- `musa_gpu_kern_gb_sum` - GPU kernel 数据传输汇总
- `musa_gpu_mem_size_sum` - GPU 内存大小汇总
- `musa_gpu_sum` - GPU 汇总
- `musa_kern_exec_sum` - Kernel 执行汇总

### 自动分析优化机会
```bash
msys analyze report.msys-rep

# 指定分析规则
msys analyze --rule=musa_memcpy_async,musa_memset_sync,musa_gpu_gaps report.msys-rep

# 查看所有可用规则
msys analyze --help-rules ALL
```

**可用分析规则：**
- `musa_memcpy_async` - 检测可异步化的内存拷贝
- `musa_memcpy_sync` - 检测同步内存拷贝问题
- `musa_memset_sync` - 检测 memset 同步问题
- `musa_api_sync` - 检测 API 同步问题
- `musa_gpu_gaps` - 检测 GPU 空闲时段
- `musa_gpu_time_util` - GPU 时间利用率分析

## 命令行选项速查

| 选项 | 说明 |
|------|------|
| `profile` | 运行应用并收集事件 |
| `launch` | 交互模式启动应用 |
| `start` | 交互模式开始收集 |
| `stop` | 交互模式停止收集 |
| `-d, --device` | 指定 GPU 设备 ID |
| `--duration` | 捕获时长 (秒) |
| `-e, --env-var` | 设置环境变量 |
| `--gpu-metrics-set` | GPU 指标集 |
| `--osrt-threshold` | OS Runtime API 的最短记录时长（ns）；过低会显著增大开销和报告 |
| `-o, --out` | 输出文件名 |
| `-t, --trace` | 追踪 API 类型；完整程序默认 `musa,osrt,mttx` |
| `-y, --delay` | 延迟启动 (秒) |

## 典型场景

### 场景 1: MUSA 应用性能分析
```bash
msys profile --duration=30 --trace=musa,osrt,mttx --osrt-threshold=1000 \
  --gpu-metrics-set=all -e LD_LIBRARY_PATH=/usr/local/musa/lib \
  -o musa_profiling ./my_musa_app
```

### 场景 2: OpenGL 应用分析
```bash
msys profile --trace=opengl -o opengl_app ./my_gl_app
```

### 场景 3: 定位 GPU 空闲问题
```bash
# 捕获包含 CPU/OS Runtime、MTTX 和 MUSA 的完整 trace
msys profile --trace=musa,osrt,mttx --osrt-threshold=1000 -o full_trace ./app

# 分析 GPU gaps
msys analyze --rule=musa_gpu_gaps full_trace.msys-rep
```

### 场景 4: 多进程应用分析
```bash
# MPI 应用
mpirun -n 4 msys profile -o rank_%h.msys-rep ./my_mpi_app
```

### 场景 5: 远程环境运行 MUSA 程序
```bash
ssh <user>@<host> 'export LD_LIBRARY_PATH=/usr/local/musa/lib:$LD_LIBRARY_PATH && msys profile -o /tmp/remote_profile /tmp/my_musa_app'
scp <user>@<host>:/tmp/remote_profile.msys-rep ./remote_profile.msys-rep
```
- 远程分析时默认先补 `LD_LIBRARY_PATH=/usr/local/musa/lib:$LD_LIBRARY_PATH`
- 如果远端已经安装 Moore Perf System，优先直接使用远端的 `msys` 命令
