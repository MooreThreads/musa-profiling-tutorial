# bound_demo_musa

无参数的单条处理管线。一次运行按 batch 循环：

```
cpu_generate -> H2D (重复) -> blur -> gemm (重复) -> D2H (重复) -> checksum
```

同一份数据沿管线走。CPU 循环、同步拷贝、设备端 GEMM 都在每个 batch 中。

## 构建

MUSA（S5000）：

```bash
make musa
./bound_demo_musa
```
