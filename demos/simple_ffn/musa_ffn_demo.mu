#include <musa_runtime.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#ifndef FFN_W2_VERSION
#    define FFN_W2_VERSION 1
#endif

#define CHECK_MUSA(x)                                                                                     \
    do {                                                                                                  \
        musaError_t e = (x);                                                                              \
        if (e != musaSuccess) {                                                                           \
            std::fprintf(stderr, "MUSA error at %s:%d: %s\n", __FILE__, __LINE__, musaGetErrorString(e)); \
            return 2;                                                                                     \
        }                                                                                                 \
    } while (0)

constexpr int M = 4096;
constexpr int K1 = 512;
constexpr int H = 2048;
constexpr int K2 = H;
constexpr int N = 1024;
constexpr int TILE = 16;

__global__ void fill_input_kernel(float *x, float *w, int count, float seed)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < count) {
        float v = static_cast<float>((i * 17 + static_cast<int>(seed)) % 101);
        x[i] = (v - 50.0f) * 0.01f;
        w[i] = (v - 25.0f) * 0.005f;
    }
}

__global__ void fill_vector_kernel(float *x, int count, float seed)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < count) {
        float v = static_cast<float>((i * 29 + static_cast<int>(seed)) % 101);
        x[i] = (v - 50.0f) * 0.01f;
    }
}

template <int TN>
__global__ void matmul_w1_kernel(const float *__restrict__ a, const float *__restrict__ b, float *__restrict__ c, int m,
                                 int k, int n)
{
    __shared__ float as[TILE][TILE];
    __shared__ float bs[TILE][TILE];
    int row = blockIdx.y * TILE + threadIdx.y;
    int col = blockIdx.x * TILE + threadIdx.x;
    float acc = 0.0f;
    for (int t = 0; t < (k + TILE - 1) / TILE; ++t) {
        int ak = t * TILE + threadIdx.x;
        int bk = t * TILE + threadIdx.y;
        as[threadIdx.y][threadIdx.x] = (row < m && ak < k) ? a[row * k + ak] : 0.0f;
        bs[threadIdx.y][threadIdx.x] = (bk < k && col < n) ? b[bk * n + col] : 0.0f;
        __syncthreads();
#pragma unroll
        for (int j = 0; j < TILE; ++j) acc += as[threadIdx.y][j] * bs[j][threadIdx.x];
        __syncthreads();
    }
    if (row < m && col < n) c[row * n + col] = acc;
}

template <int TN>
__global__ void matmul_w2_kernel_baseline(const float *__restrict__ a, const float *__restrict__ b,
                                          float *__restrict__ c, int m, int k, int n)
{
    // 基线采用偏保守的 launch 配置：block=(8,8)，tile=8。
    // 该配置结果正确，但 block 数量较多，单个 block 承担的工作量较少。
    constexpr int BASE_TILE = 8;
    __shared__ float as[BASE_TILE][BASE_TILE];
    __shared__ float bs[BASE_TILE][BASE_TILE];
    int row = blockIdx.y * BASE_TILE + threadIdx.y;
    int col = blockIdx.x * BASE_TILE + threadIdx.x;
    float acc = 0.0f;
    for (int t = 0; t < (k + BASE_TILE - 1) / BASE_TILE; ++t) {
        int ak = t * BASE_TILE + threadIdx.x;
        int bk = t * BASE_TILE + threadIdx.y;
        as[threadIdx.y][threadIdx.x] = (row < m && ak < k) ? a[row * k + ak] : 0.0f;
        bs[threadIdx.y][threadIdx.x] = (bk < k && col < n) ? b[bk * n + col] : 0.0f;
        __syncthreads();
#pragma unroll
        for (int j = 0; j < BASE_TILE; ++j) {
            acc += as[threadIdx.y][j] * bs[j][threadIdx.x];
        }
        __syncthreads();
    }
    if (row < m && col < n) c[row * n + col] = acc;
}

// v2：采用更大的 launch 配置，但每个线程仍计算一个输出。
template <int TN>
__global__ void matmul_w2_kernel_one_output(const float *__restrict__ a, const float *__restrict__ b,
                                            float *__restrict__ c, int m, int k, int n)
{
    __shared__ float as[TILE][TILE];
    __shared__ float bs[TILE][TILE];
    int row = blockIdx.y * TILE + threadIdx.y;
    int col = blockIdx.x * TILE + threadIdx.x;
    float acc = 0.0f;
    for (int t = 0; t < (k + TILE - 1) / TILE; ++t) {
        int ak = t * TILE + threadIdx.x;
        int bk = t * TILE + threadIdx.y;
        as[threadIdx.y][threadIdx.x] = (row < m && ak < k) ? a[row * k + ak] : 0.0f;
        bs[threadIdx.y][threadIdx.x] = (bk < k && col < n) ? b[bk * n + col] : 0.0f;
        __syncthreads();
#pragma unroll
        for (int j = 0; j < TILE; ++j) acc += as[threadIdx.y][j] * bs[j][threadIdx.x];
        __syncthreads();
    }
    if (row < m && col < n) c[row * n + col] = acc;
}

// v3/v4：一个 16x16 block 计算 16x32 的输出 tile。
// 每个线程负责两个相邻的输出列，使加载到寄存器中的 A 值能够复用于两次乘加，
// 同时让多个线程复用 B tile。
template <int TN>
__global__ void matmul_w2_kernel_optimized(const float *__restrict__ a, const float *__restrict__ b,
                                           float *__restrict__ c, int m, int k, int n)
{
    __shared__ float as[TILE][TILE];
#if FFN_W2_VERSION == 4
    // v4 将行跨度扩展为 33 个 float，通过 padding 改变 bank 映射并消除冲突。
    __shared__ float bs[TILE][2 * TILE + 1];
#else
    // v3 使用 bs[16][32]。由于每行跨度正好是 32 个 float，
    // 一个 warp 覆盖的两行线程会映射到重叠的 shared-memory bank，产生 bank conflict。
    __shared__ float bs[TILE][2 * TILE];
#endif
    int row = blockIdx.y * TILE + threadIdx.y;
    int col0 = blockIdx.x * (2 * TILE) + threadIdx.x * 2;
    float acc0 = 0.0f;
    float acc1 = 0.0f;
    for (int t = 0; t < (k + TILE - 1) / TILE; ++t) {
        int ak = t * TILE + threadIdx.x;
        int bk = t * TILE + threadIdx.y;
        as[threadIdx.y][threadIdx.x] = (row < m && ak < k) ? a[row * k + ak] : 0.0f;
        int bcol0 = blockIdx.x * (2 * TILE) + threadIdx.x * 2;
        bs[threadIdx.y][threadIdx.x * 2] = (bk < k && bcol0 < n) ? b[bk * n + bcol0] : 0.0f;
        bs[threadIdx.y][threadIdx.x * 2 + 1] = (bk < k && bcol0 + 1 < n) ? b[bk * n + bcol0 + 1] : 0.0f;
        __syncthreads();
#pragma unroll
        for (int j = 0; j < TILE; ++j) {
            float av = as[threadIdx.y][j];
            acc0 += av * bs[j][threadIdx.x * 2];
            acc1 += av * bs[j][threadIdx.x * 2 + 1];
        }
        __syncthreads();
    }
    if (row < m && col0 < n) c[row * n + col0] = acc0;
    if (row < m && col0 + 1 < n) c[row * n + col0 + 1] = acc1;
}

__global__ void bias_add_kernel(float *x, const float *bias, int rows, int cols)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < rows * cols) x[i] += bias[i % cols];
}

__global__ void gelu_kernel(float *x, int count)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < count) {
        float v = x[i];
        x[i] = 0.5f * v * (1.0f + tanhf(0.79788456f * (v + 0.044715f * v * v * v)));
    }
}

__global__ void relu_kernel(float *x, int count)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < count && x[i] < 0.0f) x[i] = 0.0f;
}

__global__ void row_sum_kernel(const float *x, float *sums, int rows, int cols)
{
    int row = blockIdx.x;
    if (row >= rows) return;
    float sum = 0.0f;
    for (int col = threadIdx.x; col < cols; col += blockDim.x) sum += x[row * cols + col];
    __shared__ float smem[256];
    smem[threadIdx.x] = sum;
    __syncthreads();
    for (int s = blockDim.x / 2; s > 0; s >>= 1) {
        if (threadIdx.x < s) smem[threadIdx.x] += smem[threadIdx.x + s];
        __syncthreads();
    }
    if (threadIdx.x == 0) sums[row] = smem[0];
}

__global__ void layer_norm_kernel(float *x, const float *row_sum, int rows, int cols)
{
    int row = blockIdx.x;
    if (row >= rows) return;
    float mean = row_sum[row] / cols;
    for (int col = threadIdx.x; col < cols; col += blockDim.x) {
        int i = row * cols + col;
        x[i] = (x[i] - mean) * 0.5f;
    }
}

int main()
{
    const int block = 256;
    auto grid1 = (M * K1 + block - 1) / block;
    auto gridH = (M * H + block - 1) / block;
    auto gridN = (M * N + block - 1) / block;
    float *x = nullptr, *w1 = nullptr, *h = nullptr, *w2 = nullptr, *y = nullptr;
    float *b1 = nullptr, *b2 = nullptr, *sums = nullptr;
    auto alloc = [](float **p, size_t n) { return musaMalloc(reinterpret_cast<void **>(p), n * sizeof(float)); };
    CHECK_MUSA(alloc(&x, M * K1));
    CHECK_MUSA(alloc(&w1, K1 * H));
    CHECK_MUSA(alloc(&h, M * H));
    CHECK_MUSA(alloc(&w2, K2 * N));
    CHECK_MUSA(alloc(&y, M * N));
    CHECK_MUSA(alloc(&b1, H));
    CHECK_MUSA(alloc(&b2, N));
    CHECK_MUSA(alloc(&sums, M));
    fill_input_kernel<<<(M * K1 + block - 1) / block, block>>>(x, w1, M * K1, 1.0f);
    fill_input_kernel<<<(K2 * N + block - 1) / block, block>>>(w2, w2, K2 * N, 2.0f);
    fill_vector_kernel<<<(H + block - 1) / block, block>>>(b1, H, 3.0f);
    fill_vector_kernel<<<(N + block - 1) / block, block>>>(b2, N, 4.0f);
    matmul_w1_kernel<H><<<dim3((H + TILE - 1) / TILE, (M + TILE - 1) / TILE), dim3(TILE, TILE)>>>(x, w1, h, M, K1, H);
    bias_add_kernel<<<gridH, block>>>(h, b1, M, H);
    gelu_kernel<<<gridH, block>>>(h, M * H);
#if FFN_W2_VERSION == 4
    matmul_w2_kernel_optimized<N>
        <<<dim3((N + 2 * TILE - 1) / (2 * TILE), (M + TILE - 1) / TILE), dim3(TILE, TILE)>>>(h, w2, y, M, K2, N);
#elif FFN_W2_VERSION == 3
    matmul_w2_kernel_optimized<N>
        <<<dim3((N + 2 * TILE - 1) / (2 * TILE), (M + TILE - 1) / TILE), dim3(TILE, TILE)>>>(h, w2, y, M, K2, N);
#elif FFN_W2_VERSION == 2
    matmul_w2_kernel_one_output<N>
        <<<dim3((N + TILE - 1) / TILE, (M + TILE - 1) / TILE), dim3(TILE, TILE)>>>(h, w2, y, M, K2, N);
#else
    matmul_w2_kernel_baseline<N><<<dim3((N + 8 - 1) / 8, (M + 8 - 1) / 8), dim3(8, 8)>>>(h, w2, y, M, K2, N);
#endif
    bias_add_kernel<<<gridN, block>>>(y, b2, M, N);
    relu_kernel<<<gridN, block>>>(y, M * N);
    row_sum_kernel<<<M, block>>>(y, sums, M, N);
    layer_norm_kernel<<<M, block>>>(y, sums, M, N);
    CHECK_MUSA(musaGetLastError());
    CHECK_MUSA(musaDeviceSynchronize());
    std::vector<float> host_y(static_cast<size_t>(M) * N);
    CHECK_MUSA(musaMemcpy(host_y.data(), y, host_y.size() * sizeof(float), musaMemcpyDeviceToHost));
    double checksum = 0.0;
    for (float v : host_y) checksum += v;
    std::printf("FFN demo complete: M=%d K1=%d H=%d N=%d checksum=%.9f\n", M, K1, H, N, checksum);
    CHECK_MUSA(musaFree(x));
    CHECK_MUSA(musaFree(w1));
    CHECK_MUSA(musaFree(h));
    CHECK_MUSA(musaFree(w2));
    CHECK_MUSA(musaFree(y));
    CHECK_MUSA(musaFree(b1));
    CHECK_MUSA(musaFree(b2));
    CHECK_MUSA(musaFree(sums));
    return 0;
}
