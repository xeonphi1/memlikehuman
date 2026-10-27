# DeepSeek Harness × 大鲸鱼 × MemLikeHuman

让大鲸鱼在新会话、进程重启和换模型后，继续使用同一份本地记忆。

[返回首页](../README.md) · [English](deepseek-harness.md) · [可复制的 Cordis 配置](../examples/deepseek-harness.cordis.yml)

本文中的“大鲸鱼”指社区项目 [linsport/dsh-whale-persona](https://github.com/linsport/dsh-whale-persona)（鲸鱼娘模式，preset ID 为 `whale`）。MemLikeHuman 是独立项目，与 DeepSeek、Graphiti 或该社区预设没有官方合作关系。本仓库不分发上游人设全文、商标图片或角色美术。

## 1. 安装并初始化

需要 Python 3.11+、支持 FTS5 的 SQLite，以及已能运行的 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。在终端执行：

```sh
git clone https://github.com/xeonphi1/memlikehuman.git
cd memlikehuman
uv sync --frozen
uv run memlikehuman --data-dir /ABSOLUTE/PATH/private/memlikehuman --persona whale init
uv run memlikehuman --data-dir /ABSOLUTE/PATH/private/memlikehuman --persona whale persona --file examples/whale-memory-persona.json
uv run memlikehuman --data-dir /ABSOLUTE/PATH/private/memlikehuman doctor
```

替换 `/ABSOLUTE/PATH/private/memlikehuman` 为仓库之外的私人数据目录。Windows 可用 `C:/Users/YOU/AppData/Local/MemLikeHuman`；JSON/YAML 里用正斜杠能避免转义问题。没有 uv 时可在虚拟环境中 `python -m pip install .`。

示例人格是原创、简短的记忆行为约定，避免默认“知伴”名称与宿主鲸鱼人设冲突。它没有复制鲸鱼娘的完整角色设定。若希望离开 Harness 后也携带完整角色风格，请在本地按 `Persona` 的 `name/traits/values/style/boundaries` 格式整理你有权使用的人设，再用 `persona --file` 保存。不能仅凭加载记忆就保证任何模型逐字复现原角色。

## 2. 添加 MCP 服务

复制 [deepseek-harness.cordis.yml](../examples/deepseek-harness.cordis.yml) 到私人配置目录，替换里面的程序路径和数据路径。

| 平台 | `command` 示例 |
|---|---|
| macOS / Linux | `/absolute/path/memlikehuman/.venv/bin/memlikehuman` |
| Windows | `C:/absolute/path/memlikehuman/.venv/Scripts/memlikehuman.exe` |

`command` 和 `args` 由宿主直接启动，不经过 shell。不要在其中使用 `~`、`$HOME` 或把整个命令写进 `command`。

临时验证：

```sh
dsh web --patch /ABSOLUTE/PATH/private/deepseek-harness.cordis.yml
```

如果使用 `npx` 启动，则是：

```sh
npx @deepseek-ai/dsh web --patch /ABSOLUTE/PATH/private/deepseek-harness.cordis.yml
```

长期使用：先备份已有文件，将示例的**一个 `- insert:` 块**合并到相应的用户补丁文件，不要覆盖已有补丁：

- Web：`~/.dsh/profiles/web/cordis.patch.yml`
- Desktop：`~/.dsh/profiles/desktop/cordis.patch.yml`
- 设置过 `DSH_HOME` 时，将上述 `~/.dsh` 换成该目录。

已有鲸鱼补丁时，保留 `preset-whale` 那一块，并在同一个 YAML 列表中添加本例的 `insert` 块。尚未安装鲸鱼预设时，按[上游说明](https://github.com/linsport/dsh-whale-persona#readme)安装，再添加本服务。不要把通用 `mcpServers` JSON 粘进 Cordis YAML。

重启 Harness，新建一个空会话，选择“鲸鱼娘模式”。本示例的 MCP 插件注册在宿主层，其他预设也可能看到这些工具；数据隔离靠每次工具调用中明确的 `persona_id` 和 `project_id`，并非预设名称自动推导。

## 3. 让鲸鱼知道什么时候用记忆

Harness 当前不支持 MCP prompt templates，所以不能依赖 `start_session` 模板自动启动。把 [whale-host-instructions.txt](../examples/whale-host-instructions.txt) 的内容追加到你现有人设或会话指令中，保留原来的鲸鱼人设。也可先作为新会话第一条消息发送，验证流程。

必须出现以下工具（名称由 `serverName: memlikehuman` 决定）：

| 操作 | Harness 中的工具 |
|---|---|
| 恢复人格和工作 | `mcp__memlikehuman__session_resume` |
| 写入原始经历 | `mcp__memlikehuman__memory_record` |
| 查找旧记忆 | `mcp__memlikehuman__memory_recall` |
| 翻日记原文 | `mcp__memlikehuman__memory_read` |
| 保存交接 | `mcp__memlikehuman__session_checkpoint` |
| 用户要求的纠错／删除 | `mcp__memlikehuman__memory_correct` / `memory_forget`（同名前缀） |

每次传入固定的 `persona_id="whale"` 和 `project_id="companionship"`。工作项目可以另选 `project_id="my-app"`；同一人格跨项目共享核心人格，但不共享项目事件与待办。CLI 的 `--persona` 不会改变 MCP 工具参数的默认值。

首次恢复的参数示例：

```json
{"persona_id":"whale","project_id":"companionship","token_budget":8000}
```

默认预算估算较保守；检查 `counting_method`、`omitted`、`warnings`。预算只约束返回的 `context` 字符串，宿主自己的聊天、人设、工具定义和 MCP 包装还需要另留空间。

## 4. 可选：配置自动提炼

不配 API 也可以持久化原文、关键词查找、翻日记和恢复工作。原文显示 `pending` 是正常状态。丰富的事实、约定、成长和概览，需要提炼 API，或用 CLI `derive` 导入经检查的结果。

复制并编辑 [config.json](../examples/config.json)，选择账户实际可用、支持 JSON 输出的模型。然后：

```sh
uv run memlikehuman --data-dir /ABSOLUTE/PATH/private/memlikehuman config --file /ABSOLUTE/PATH/private/config.json
```

在启动 Harness 的环境中设置 `MEMLIKEHUMAN_API_KEY`。示例的 `env` 显式转发这个变量：**Harness 会过滤环境中的 KEY/TOKEN 等凭证变量，单纯在父进程设置 key 不够。** 桌面程序从图标启动时也可能没有终端的环境变量，应使用其支持的环境配置或从已设置变量的终端启动。不要把真实 key 提交到仓库。

Harness 的聊天模型与 MemLikeHuman 的提炼模型分别配置。配置提炼后，写入会先落盘再等待 API，默认超时 30 秒；失败保留原文，之后执行：

```sh
uv run memlikehuman --data-dir /ABSOLUTE/PATH/private/memlikehuman --persona whale --project companionship retry
```

查询默认 `fast`，恢复也走本地路径，不因为配置了 embedding 就在每次换模型时调用远端 API。显式 `semantic` 检索近期向量，`deep` 检索所有已建索引向量；后者可能较慢。

## 5. 三步验收，确认它真的记住了

1. 会话 A：发送“请记住：本次合成测试的暗号是蓝鲸茶杯-731。用 MemLikeHuman 保存，persona_id=whale，project_id=companionship。”检查实际工具调用和 `durable: true`，不要只看模型口头答应。记录返回的事件 ID。
2. 新建会话 B，仍选择鲸鱼预设，发送“调用 MemLikeHuman 查找‘暗号’，使用同一人格和项目。”检查 `memory_recall` 返回的来源；未提炼时也应有 `raw_events`，必要时调用 `memory_read`。确认能找回 `蓝鲸茶杯-731`。
3. 保持数据目录、人格和项目不变，换一个支持工具调用的聊天模型，重复第 2 步。比较关键事实、约定和边界，不要求逐字相同。真实模型是否遵守调用指令，需要你在所用模型上验证。

工作交接另测：在 A 中记录一个任务事件，保存带有 `goal`、`completed`、`pending`、`constraints`、`next_step` 的 checkpoint，并填入该会话的 `covered_event_id`。B 的 `session_resume` 应返回该下一步。

这是工具协作约定；通用 MCP 不能自动截获全部对话，也无法自行感知上下文快满。后续宿主插件才适合提供强制的自动捕获和压缩前交接。

## 与 dsh-mnemon 共存

鲸鱼项目可能已启用 `dsh-mnemon`。它的“记忆空间”等设置属于另一套插件，不能直接当成 MemLikeHuman 配置。

选择清楚的职责：例如让 MemLikeHuman 保存长期人格、经历和工作交接，避免同一内容被两套记忆反复写入和重复注入。保留原有数据；若要停用另一套自动记忆功能，先按其文档备份并调整配置。本项目不自动迁移或删除 mnemon 数据。

## 常见问题

| 现象 | 检查方法 |
|---|---|
| 工具列表中没有服务 | 检查绝对程序路径、YAML 缩进和 Harness 日志；先在终端运行同一命令，正常 stdio 服务会等待输入 |
| 终端有 key，宿主却报无权限 | 检查示例 `env` 转发、变量名与实际启动环境；修改后重启服务 |
| 换会话后找不到记忆 | 对比 data-dir、persona_id、project_id；确认旧会话确实调用过写入工具 |
| 恢复预算不足 | 根据 `required_core_tokens` 增大预算，或由用户通过 CLI 编辑核心人格 |
| 旧经历只返回概览 | 正常淡忘；用记录 ID 调 `memory_read`，或 recall 的 `detail="detailed"` |
| 开启 API 后写入变慢 | 原文仍先落盘；慢的是同步提炼／向量 API，与本地恢复基准不同 |

## 核对范围与来源

配置字段、命名、环境转发和 overlay 格式已按上游文档与源码核对（2026-10-27）；本地验证了官方 Python SDK 的真实 stdio 握手、工具发现与调用。**没有宣称已经在真实 Harness UI、鲸鱼预设和付费模型上完成端到端测试。** 上游仍在变化，请对照你安装的版本。

- [Harness MCP 客户端文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)
- [Harness MCP 客户端配置源码](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/src/index.ts)
- [Harness 第三方记忆服务指南](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/mcp-memory.md)
- [鲸鱼预设与安装说明](https://github.com/linsport/dsh-whale-persona)
