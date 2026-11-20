# MUSA Profiling Tutorial

本仓库用于沉淀摩尔线程 MUSA profiling 工具的示例、教程和实践经验，帮助开发者理解 profiling 工作流。

## 项目状态

仓库目前处于初始阶段。后续会持续增加不同场景下的 demo 和教程，覆盖 profiling 工具的使用方法、指标解读、问题定位和优化实践。

## 仓库组织

每个 demo 或教程都在独立目录中维护，并通过目录内的 `README.md` 说明背景、环境要求、运行步骤和分析方法。根目录 README 只描述仓库整体定位和协作方式，具体示例细节请以对应目录的文档为准。

新增内容时，建议保持以下结构：

```text
demos/<name>/
├── README.md       # 示例说明、运行方法和 profiling 结果
└── ...             # 源码、脚本或其他配套文件
```

## 面向社区持续改进

欢迎通过 Issue 或 Pull Request 反馈以下内容：

- profiling 工具使用过程中遇到的问题和不清晰之处；
- 希望补充的硬件指标、分析场景或教程主题；
- 示例代码、采集配置和文档的改进建议；
- 不同环境下的结果差异及可复现信息。

社区反馈将用于改进示例和教程，也用于推动 profiling 工具的使用体验持续完善。提交反馈时，请尽量附上 MUSA、驱动、GPU 型号、工具版本、运行命令和相关报告信息。

## AI Agent 友好

AI Agent 友好是 Moore Perf Profiling Toolkits 关键目标之一，demo 不会局限于人工 profiling，也欢迎社区积极反馈结合 AI 使用的痛点和需求。

## Moore Perf Tools 文档

摩尔线程开发者工具 Moore Perf Tools 的官方文档首页：[https://docs.mthreads.com/mooreperf/mooreperf-doc-online/introduction](https://docs.mthreads.com/mooreperf/mooreperf-doc-online/introduction)。

## 许可证

本项目采用 [MIT License](LICENSE)。