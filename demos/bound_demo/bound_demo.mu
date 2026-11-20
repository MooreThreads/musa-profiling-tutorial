#include <musa_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define MUSA_CHECK(call)                                                     \
  do {                                                                       \
    musaError_t status__ = (call);                                           \
    if (status__ != musaSuccess) {                                           \
      std::fprintf(stderr, "CUDA call failed: %s (%s:%d): %s\n", #call,      \
                   __FILE__, __LINE__, musaGetErrorString(status__));        \
      std::exit(EXIT_FAILURE);                                               \
    }                                                                        \
  } while (0)

namespace {

// 单条处理管线:
//   cpu_generate -> H2D -> blur -> gemm -> D2H -> checksum
// 常数选成一次运行里各段都看得见, 不靠命令行切换。
constexpr int kImageW = 2048;
constexpr int kImageH = 2048;
constexpr int kCpuIters = 32;
constexpr int kXferRepeat = 8;
constexpr int kGemmN = 2048;
constexpr int kGemmRepeats = 4;
constexpr int kWarmup = 1;
constexpr int kBatches = 2;

// 演示基线：tile=16 用于展示诊断与调优流程，非生产配置。
constexpr int kGemmTile = 16;
constexpr int kBlurBlockX = 32;
constexpr int kBlurBlockY = 8;

__device__ __forceinline__ float load_clamp(const float* in, int width,
                                            int height, int x, int y) {
  x = x < 0 ? 0 : (x >= width ? width - 1 : x);
  y = y < 0 ? 0 : (y >= height ? height - 1 : y);
  return in[static_cast<size_t>(y) * static_cast<size_t>(width) +
            static_cast<size_t>(x)];
}

extern "C" __global__ void blur_rows(const float* in, float* out, int width,
                                     int height) {
  int x = static_cast<int>(blockIdx.x * blockDim.x + threadIdx.x);
  int y = static_cast<int>(blockIdx.y * blockDim.y + threadIdx.y);
  if (x >= width || y >= height) {
    return;
  }
  const float inv = 1.0f / 16.0f;
  float acc = 1.0f * load_clamp(in, width, height, x - 2, y) +
              4.0f * load_clamp(in, width, height, x - 1, y) +
              6.0f * load_clamp(in, width, height, x, y) +
              4.0f * load_clamp(in, width, height, x + 1, y) +
              1.0f * load_clamp(in, width, height, x + 2, y);
  out[static_cast<size_t>(y) * static_cast<size_t>(width) +
      static_cast<size_t>(x)] = acc * inv;
}

extern "C" __global__ void blur_cols(const float* in, float* out, int width,
                                     int height) {
  int x = static_cast<int>(blockIdx.x * blockDim.x + threadIdx.x);
  int y = static_cast<int>(blockIdx.y * blockDim.y + threadIdx.y);
  if (x >= width || y >= height) {
    return;
  }
  const float inv = 1.0f / 16.0f;
  float acc = 1.0f * load_clamp(in, width, height, x, y - 2) +
              4.0f * load_clamp(in, width, height, x, y - 1) +
              6.0f * load_clamp(in, width, height, x, y) +
              4.0f * load_clamp(in, width, height, x, y + 1) +
              1.0f * load_clamp(in, width, height, x, y + 2);
  out[static_cast<size_t>(y) * static_cast<size_t>(width) +
      static_cast<size_t>(x)] = acc * inv;
}

extern "C" __global__ void tiled_gemm(const float* A, const float* B, float* C,
                                      int n) {
  __shared__ float tile_a[kGemmTile][kGemmTile];
  __shared__ float tile_b[kGemmTile][kGemmTile];

  int row = static_cast<int>(blockIdx.y * kGemmTile + threadIdx.y);
  int col = static_cast<int>(blockIdx.x * kGemmTile + threadIdx.x);
  float sum = 0.0f;
  int tiles = (n + kGemmTile - 1) / kGemmTile;

  for (int t = 0; t < tiles; ++t) {
    int a_col = t * kGemmTile + static_cast<int>(threadIdx.x);
    int b_row = t * kGemmTile + static_cast<int>(threadIdx.y);
    tile_a[threadIdx.y][threadIdx.x] =
        (row < n && a_col < n)
            ? A[static_cast<size_t>(row) * static_cast<size_t>(n) +
                static_cast<size_t>(a_col)]
            : 0.0f;
    tile_b[threadIdx.y][threadIdx.x] =
        (b_row < n && col < n)
            ? B[static_cast<size_t>(b_row) * static_cast<size_t>(n) +
                static_cast<size_t>(col)]
            : 0.0f;
    __syncthreads();
#pragma unroll
    for (int k = 0; k < kGemmTile; ++k) {
      sum += tile_a[threadIdx.y][k] * tile_b[k][threadIdx.x];
    }
    __syncthreads();
  }

  if (row < n && col < n) {
    C[static_cast<size_t>(row) * static_cast<size_t>(n) +
      static_cast<size_t>(col)] = sum;
  }
}

void cpu_generate(float* image, int width, int height, int frame, int iters) {
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float v = 0.002f * static_cast<float>((x + frame * 17) & 255) +
                0.001f * static_cast<float>((y + frame * 9) & 127);
      for (int i = 0; i < iters; ++i) {
        v = v * 1.000000119f + 0.000001f * static_cast<float>((i + x) & 31);
      }
      image[static_cast<size_t>(y) * static_cast<size_t>(width) +
            static_cast<size_t>(x)] = v;
    }
  }
}

void fill_matrix(float* mat, int n, int seed) {
  for (int i = 0; i < n * n; ++i) {
    mat[i] = 0.001f * static_cast<float>(((i + seed) % 1009) - 500);
  }
}

double checksum(const float* data, int count) {
  double sum = 0.0;
  int stride = std::max(1, count / 4096);
  for (int i = 0; i < count; i += stride) {
    sum += static_cast<double>(data[i]);
  }
  return sum;
}

}  // namespace

int main() {
  int device_count = 0;
  MUSA_CHECK(musaGetDeviceCount(&device_count));
  if (device_count <= 0) {
    std::fprintf(stderr, "No CUDA/MUSA device found.\n");
    return EXIT_FAILURE;
  }
  MUSA_CHECK(musaSetDevice(0));
  musaDeviceProp prop{};
  MUSA_CHECK(musaGetDeviceProperties(&prop, 0));
  std::printf("GPU: %s (SM %d.%d, %.1f GiB)\n", prop.name, prop.major,
              prop.minor, prop.totalGlobalMem / (1024.0 * 1024.0 * 1024.0));
  std::printf(
      "pipeline: cpu_generate -> H2D x%d -> blur -> gemm x%d -> D2H x%d -> "
      "checksum\n",
      kXferRepeat, kGemmRepeats, kXferRepeat);
  std::printf("image=%dx%d cpu_iters=%d gemm=%d warmup=%d batches=%d\n",
              kImageW, kImageH, kCpuIters, kGemmN, kWarmup, kBatches);

  const size_t image_count =
      static_cast<size_t>(kImageW) * static_cast<size_t>(kImageH);
  const size_t image_bytes = image_count * sizeof(float);
  const size_t gemm_count =
      static_cast<size_t>(kGemmN) * static_cast<size_t>(kGemmN);
  const size_t gemm_bytes = gemm_count * sizeof(float);

  float* h_in = static_cast<float*>(std::malloc(image_bytes));
  float* h_out = static_cast<float*>(std::malloc(image_bytes));
  float* h_A = static_cast<float*>(std::malloc(gemm_bytes));
  float* h_B = static_cast<float*>(std::malloc(gemm_bytes));
  if (!h_in || !h_out || !h_A || !h_B) {
    std::fprintf(stderr, "malloc failed\n");
    return EXIT_FAILURE;
  }

  float* d_in = nullptr;
  float* d_tmp = nullptr;
  float* d_out = nullptr;
  float* d_A = nullptr;
  float* d_B = nullptr;
  float* d_C = nullptr;
  MUSA_CHECK(musaMalloc(&d_in, image_bytes));
  MUSA_CHECK(musaMalloc(&d_tmp, image_bytes));
  MUSA_CHECK(musaMalloc(&d_out, image_bytes));
  MUSA_CHECK(musaMalloc(&d_A, gemm_bytes));
  MUSA_CHECK(musaMalloc(&d_B, gemm_bytes));
  MUSA_CHECK(musaMalloc(&d_C, gemm_bytes));

  fill_matrix(h_A, kGemmN, 3);
  fill_matrix(h_B, kGemmN, 11);
  MUSA_CHECK(musaMemcpy(d_A, h_A, gemm_bytes, musaMemcpyHostToDevice));
  MUSA_CHECK(musaMemcpy(d_B, h_B, gemm_bytes, musaMemcpyHostToDevice));

  dim3 blur_block(kBlurBlockX, kBlurBlockY);
  dim3 blur_grid((kImageW + kBlurBlockX - 1) / kBlurBlockX,
                 (kImageH + kBlurBlockY - 1) / kBlurBlockY);
  dim3 gemm_block(kGemmTile, kGemmTile);
  dim3 gemm_grid((kGemmN + kGemmTile - 1) / kGemmTile,
                 (kGemmN + kGemmTile - 1) / kGemmTile);

  const int total = kWarmup + kBatches;

  for (int batch = 0; batch < total; ++batch) {
    if (batch == kWarmup) {
      MUSA_CHECK(musaDeviceSynchronize());
    }

    cpu_generate(h_in, kImageW, kImageH, batch, kCpuIters);

    for (int r = 0; r < kXferRepeat; ++r) {
      MUSA_CHECK(musaMemcpy(d_in, h_in, image_bytes, musaMemcpyHostToDevice));
    }

    blur_rows<<<blur_grid, blur_block>>>(d_in, d_tmp, kImageW, kImageH);
    blur_cols<<<blur_grid, blur_block>>>(d_tmp, d_out, kImageW, kImageH);
    MUSA_CHECK(musaGetLastError());
    MUSA_CHECK(musaDeviceSynchronize());

    for (int r = 0; r < kGemmRepeats; ++r) {
      tiled_gemm<<<gemm_grid, gemm_block>>>(d_A, d_B, d_C, kGemmN);
    }
    MUSA_CHECK(musaGetLastError());
    MUSA_CHECK(musaDeviceSynchronize());

    for (int r = 0; r < kXferRepeat; ++r) {
      MUSA_CHECK(musaMemcpy(h_out, d_out, image_bytes, musaMemcpyDeviceToHost));
    }

    const double chk_val = checksum(h_out, static_cast<int>(image_count));

    std::printf("batch %d%s checksum=%.4f\n", batch,
                batch < kWarmup ? " (warmup)" : "         ", chk_val);
  }

  MUSA_CHECK(musaDeviceSynchronize());
  std::printf("OK\n");

  MUSA_CHECK(musaFree(d_in));
  MUSA_CHECK(musaFree(d_tmp));
  MUSA_CHECK(musaFree(d_out));
  MUSA_CHECK(musaFree(d_A));
  MUSA_CHECK(musaFree(d_B));
  MUSA_CHECK(musaFree(d_C));
  std::free(h_in);
  std::free(h_out);
  std::free(h_A);
  std::free(h_B);
  return EXIT_SUCCESS;
}
