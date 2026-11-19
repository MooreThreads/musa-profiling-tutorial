# Repository Guidelines

## Project Structure & Module Organization

This repository collects MUSA profiling examples and tutorials. Each demo or tutorial belongs in its own directory under `demos/` and should include a local `README.md` describing its purpose, prerequisites, build command, profiling workflow, and expected observations. Keep source files and helper scripts beside the documentation for that demo. The root `README.md` describes repository-wide scope; `LICENSE` contains the project license. There is currently no separate test or asset tree.

Use descriptive, lowercase directory names such as `demos/<topic-name>/`. Avoid placing demo-specific instructions in the root README.

## Build, Test, and Development Commands

Run commands from the relevant demo directory and document any hardware or toolchain requirements:

```bash
mcc -std=c++17 -O2 -mtgpu --cuda-gpu-arch=mp_31 \
    -o <program> <source>.mu -lmusart
```

Use `msys` to locate program-level GPU hotspots and `mcu` to profile an individual kernel. Record the exact command, tool version, GPU model, and relevant report settings in the demo README. No repository-wide build system or automated test command is currently defined.

## Coding Style & Naming Conventions

Follow the existing MUSA/C++ style: clear snake_case names for kernels and variables, consistent four-space indentation, and focused changes. Keep profiling-sensitive code reproducible; avoid unrelated changes to workload sizes, launch configuration, or compiler flags. Name report and analysis outputs descriptively and keep generated artifacts out of version control unless they are intentional fixtures.

## Testing Guidelines

Validate demos by compiling and running them in a supported MUSA environment, then checking the expected profiling reports. Compare before/after metrics using fixed inputs and launch settings. There is no formal coverage requirement or test naming convention yet; add a small reproducible validation section to each demo README.

## Commit & Pull Request Guidelines

No Git history is available in this checkout, so no established commit convention can be inferred. Use short, imperative commit subjects, for example `Add memory profiling tutorial`. Pull requests should explain the user-facing goal, list affected demos and commands, include profiling evidence or report summaries when relevant, and note hardware, driver, MUSA, and tool versions. Keep each pull request focused and update the relevant README with code changes.

## Community and Agent-Friendly Contributions

Prefer explicit directory structure, copyable commands, stable terminology, and self-contained demo READMEs. Include enough context for both human contributors and AI agents to reproduce the example and interpret its profiling results.