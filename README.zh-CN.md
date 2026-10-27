# MemLikeHuman

**让不同模型共享保存在本地的人格、经历和工作进度。**

[首页](README.md) · [English](README.en.md) · [大鲸鱼接入](docs/deepseek-harness.zh-CN.md) · [性能实测](docs/performance.md) · [架构与行为](docs/architecture.md) · [MCP 接入约定](docs/mcp.md)

这是可运行的 **v0.2 开发预览版**。核心思路是把人格与记忆保存在模型之外：新会话、重启或换模型时，按预算恢复核心人格和相关经历，需要细节再查原文。

借鉴 [Graphiti](https://github.com/getzep/graphiti) 的时间与来源设计，第一版使用 SQLite，不需要图数据库或 Docker。它不宣称赋予模型真实主观情感，也不能保证不同模型表现出完全相同的性格。

## 已实现

- **原文先落盘**：提炼 API 失败时原文仍在，之后可以重试。稳定事件 ID 防止重复记录。
- **有出处的记忆**：每条记忆关联原始事件与原文片段，区分用户陈述、助手表达和推测。
- **有时间的事实**：保留事实的有效区间，支持历史查询；补录旧经历不覆盖新事实。
- **人格与成长分离**：核心人格由用户修改、版本化保存；习惯、共同约定、情绪状态另行记录，情绪随时间回归基线。
- **检索与恢复**：中文分词、关键词检索、显式关联和可选语义向量；按预算返回人格、任务和相关记忆。
- **本地管理**：纠错、删除、人格回滚、JSON/JSONL 导入导出、SQLite 备份恢复与完整性检查。
- **通用接入**：7 个 stdio MCP 工具、人格资源、会话提示模板和命令行。

**通用 MCP 只能看到主动提交给它的事件。** 它不能截获全部聊天、检测宿主上下文是否满了，也不能强制模型调用工具。自动记录与交接需要宿主遵守调用约定；后续才能通过宿主专用插件补齐全自动流程。

## 先运行离线演示

需要 Python 3.11+，Python 自带的 SQLite 需要支持 FTS5。在项目目录执行：

```sh
uv sync --frozen --group dev
uv run python examples/demo.py --data-dir /tmp/memlikehuman-demo
uv run memlikehuman --data-dir /tmp/memlikehuman-demo --project synthetic-demo resume --budget 16000
```

演示仅使用合成中文数据：从上海搬到杭州、先测试再提交的约定、回顾待办的工作习惯、角色表达的开心、尚未确认的咖啡偏好和未完成工作。提炼结果是人工检查过的示例，不会调用模型 API。

Windows 可将 `/tmp/memlikehuman-demo` 换成一个新的本地目录。没有 uv 时可运行 `python -m pip install .` 安装；当前未发布到 PyPI。

## 迁移已有历史

已有数月聊天可按[历史迁移指南](docs/history-migration.zh-CN.md)补导：先取得真实原文、转换成事件 JSONL，再用示例脚本离线持久化，最后分批提炼。`import` 仅用于本项目备份，不接受任意平台聊天导出。

## 日常使用

```sh
uv run memlikehuman init
uv run memlikehuman record examples/event.json
uv run memlikehuman derive synthetic-demo-001 examples/extraction.json
uv run memlikehuman checkpoint examples/checkpoint.json --covered-event synthetic-demo-001 --session demo
uv run memlikehuman resume --budget 8000
```

默认数据目录是 `~/.local/share/memlikehuman/`，可用环境变量 `MEMLIKEHUMAN_HOME` 或全局参数 `--data-dir` 更换。真实对话、数据库和备份应放在代码仓库之外。

通过全局 `--persona`、`--project` 选择人格与项目。核心人格在其各项目间共享，经历与任务按人格＋项目隔离。事件 ID 应在整个本地存储中唯一，建议使用 UUID。

未配置提炼模型时，原文保存为 `pending`，仍然可读和按关键词检索。`derive` 用于导入经过本地检查的提炼结果；配置模型后用 `retry` 处理待提炼事件。角色设定和引用资料要分别标记为 `persona`、`reference`，不会被直接当成真实共同经历。

## 接入 MCP 客户端

参考 [examples/mcp.json](examples/mcp.json)，将两个绝对路径替换为本机路径。macOS/Linux 的程序位置通常为项目内 `.venv/bin/memlikehuman`，Windows 为 `.venv/Scripts/memlikehuman.exe`。

```sh
/path/to/checkout/.venv/bin/memlikehuman --data-dir /path/to/private/data serve
```

启用 `start_session` 提示模板，或将 [调用约定](docs/mcp.md) 放入宿主配置：

1. 新会话先调用 `session_resume`。
2. 用户希望保留的对话事件，使用真实说话者和原文调用 `memory_record`。
3. 需要过去的事实时调用 `memory_recall`，需要精确原文时调用 `memory_read`。
4. 已知即将压缩上下文、交接或结束工作时，调用 `session_checkpoint`。

提示模板和 MCP 服务说明都是调用建议，不是自动钩子。项目没有替你修改任何现有助手的配置。

## 接入云端模型

编辑 [examples/config.json](examples/config.json) 的副本，选择你的账户实际可用且支持 JSON 对象返回的模型。示例采用 DeepSeek 兼容聊天端点：

```sh
uv run memlikehuman config --file /path/to/private/config.json
uv run memlikehuman retry
```

启动 CLI 或 MCP 服务前，在运行环境里设置 `api_key_env` 指定的变量。配置文件只保存环境变量名称，不保存 API key；服务运行期间修改配置后需要重启。

提炼模型、embedding 模型和实际对话模型互相独立。配置提炼 API 后会发送当前原始事件；配置 embedding API 后会发送提炼出的记忆及检索问题。**本地存储不等于离线推理。** 将两个 provider 都设为 `null`，系统就不调用模型 API。

`embedding` 可以配置为包含 `base_url`、`model`、`api_key_env`、`version`、`timeout_seconds` 的对象。自动提炼出的新记忆会尝试生成向量。切换 embedding 模型或版本、恢复档案、手动提炼或更正记忆后，执行：

```sh
uv run memlikehuman reindex
```

系统不会混用不同模型指纹的向量。索引不完整或 API 不可用时会提示并使用关键词检索。默认 `fast` 检索不调用 API；显式 `semantic` 扫描近期最多 2,000 条向量并提示覆盖范围，`deep` 扫描全部有效索引向量。两种语义模式都会调用 embedding API；没有引入近似向量索引。

## 人格、纠错与备份

```sh
uv run memlikehuman persona
uv run memlikehuman persona --file examples/persona.json
uv run memlikehuman persona --rollback 1
uv run memlikehuman recall '住在哪里' --as-of 2026-02-01T00:00:00Z
uv run memlikehuman recall '住在哪里' --history
uv run memlikehuman doctor
uv run memlikehuman export /path/to/private/archive.jsonl
uv run memlikehuman backup /path/to/private/backup.sqlite3
uv run memlikehuman --data-dir /path/to/new/empty/directory restore /path/to/private/archive.jsonl
```

恢复支持 JSON、JSONL 和 SQLite 备份，目标必须是空数据目录。不会合并或覆盖旧档案。人格版本、原文、记忆、关联、情绪和交接状态全部保留；全文索引重建，向量通过 `reindex` 重建。配置与环境变量中的密钥不导出，但原始对话中已经包含的敏感内容不会被自动脱敏。

`correct MEMORY_ID --content ... --reason ...` 用于用户明确要求的纠错，保留旧版本供追溯；真实情况随时间变化时，应记录新事件。`forget RECORD_ID` 会删除来源事件、由它产生的全部记忆及更正链、关联和索引。纠错与删除都会使当前人格＋项目的全部交接摘要失效，避免恢复过期内容。

删除最新事实不会让过去已失效的事实重新成为当前事实。独立提交的副本、以前的备份和模型服务商日志不会自动清理。平常随时间“淡忘”会降低排序，并把旧经历呈现为概览；不删除原文。事实、偏好、约定、成长保持详细，旧情绪不会成为当前状态。通过 `memory_read` 可以翻阅原始日记。

数据为本地明文，使用操作系统支持的目录和文件权限保护。本服务面向单用户本地 stdio；项目隔离用于防止串记忆，不是面对恶意客户端的授权系统。来源片段能证明出处，不能证明提炼内容一定正确。

## 上下文预算

恢复优先级：完整核心人格 → 最近任务 → 共同约定与成长 → 问题相关记忆 → 当前情绪表达 → 近期事件。

返回内容包含计数方式、省略项和警告。如果核心人格本身放不下，会返回 `insufficient_budget` 和所需大小，不会悄悄截断人设。`ok` 也只表示选出的恢复内容放得下，不代表全库记忆都在里面。

安装可选的 `tokenizer` 依赖且目标模型可识别时，使用其 tokenizer 精确计算 **context 字符串**；首次使用可能下载 tokenizer 资源。未知模型或资源不可用时，退回保守的 UTF-8 字节估算并注明。计数不包含宿主已有聊天、系统提示、工具定义及 MCP 包装，调用方需要另留空间。

## 测试与构建

```sh
uv run pytest -q
uv run ruff check src tests examples benchmarks scripts
uv run ruff format --check src tests examples benchmarks scripts
uv build
```

测试覆盖真实 MCP 子进程、原文落盘后进程退出、并发幂等、事实时间线、推测隔离、人格回滚、情绪衰减、预算不足、纠错删除、向量版本和备份恢复。CI 配置覆盖 Linux/macOS/Windows 的 Python 3.11 与 3.13；配置存在不表示远程 CI 已运行。

仓库另附 `examples/eval_models.py`，可显式配置两个模型，用同一组合成记忆检查事实、约定、待办和不确定性处理。它会产生模型 API 调用费用；默认测试不调用真实模型，也不声称跨模型人格效果已经实测。具体命令见英文 README。

## 开源

采用 Apache-2.0。见 [LICENSE](LICENSE)、[NOTICE](NOTICE)、[贡献说明](CONTRIBUTING.md)。源代码仓库地址为 `xeonphi1/memlikehuman`，尚未发布到 PyPI。后续方向：宿主生命周期插件、可选 Graphiti 后端、更系统的评测和更大规模的检索。
