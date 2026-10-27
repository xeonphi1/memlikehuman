# 已经和大鲸鱼聊了 100 多天，怎样迁移旧记忆？

[首页](../README.md) · [Harness 接入](deepseek-harness.zh-CN.md) · [历史导入示例脚本](../examples/import_chat_history.py)

**可以补导历史，不要求当初已经安装 MemLikeHuman。前提是你仍拿得到旧聊天原文。** MCP 不会主动回头抓取聊天，模型也无法恢复已被上下文压缩丢掉的内容。平台导出、宿主保存的会话文件，才是迁移的起点。

```mermaid
flowchart LR
    A[备份旧聊天原始文件] --> B[转换为逐条事件 JSONL]
    B --> C[离线校验并保存全部原文]
    C --> D[小批量提炼与核对]
    D --> E[保存人格和当前交接]
    E --> F[新会话恢复 + 旧事按需查询]
    F --> G[持续写入新对话 + 备份]
```

## 第一步：把过去 100 多天的聊天取出来

使用你所用聊天平台／宿主实际支持的导出或备份方式。保留一个不修改的原始副本，再在另一份上做转换。不同软件的导出结构不同，本文不假设某个“导出”按钮一定存在，也不假设它们都能提供完整历史。

需要保留：每条消息的原文、说话者、原始时间与时区、会话标识、消息标识及来源。图片、附件另外备份；目前本服务只索引你登记的图片线索，不搬运或识别图片。

- 有完整导出：可以迁移导出中包含的记录。
- 只有部分导出／屏幕上可见的记录：只能迁移这部分；OCR 或手工复制后需核对原文、角色和时间。
- 只剩鲸鱼的一段回顾：可将其作为新的 **assistant 表达或未核实材料** 保存，不要拆成伪造的旧 user 原话，更不能宣称已经恢复了全部历史。
- 没有记录、也没有可访问的备份：本项目无法重建已丢失的聊天。

让旧会话总结关键经历可以辅助整理，但不能代替原始聊天档案。

## 第二步：转换成标准事件 JSONL

在私人目录准备 `history.events.jsonl`，**一行一个 JSON 对象，一条原始消息对应一条事件**。换行保留在 JSON 字符串内的 `\n` 中，不删除正文或改写语气。

以下两条仅为合成示例：

```jsonl
{"event_id":"dsh:profile-a:session-01:msg-001","text":"我们约定，以后修改代码先测试再提交。","role":"user","source":"dsh-export:profile-a","session_id":"session-01","category":"conversation","occurred_at":"2026-06-01T20:00:00+08:00"}
{"event_id":"dsh:profile-a:session-01:msg-002","text":"我会按这个约定做。","role":"assistant","source":"dsh-export:profile-a","session_id":"session-01","category":"conversation","occurred_at":"2026-06-01T20:00:10+08:00"}
```

转换规则：

1. `event_id` 在本地档案中必须全局唯一且可重复生成。优先组合“来源＋用户档案＋会话 ID＋消息 ID”；同一消息重新导入时使用同一 ID。不要每次重新生成 UUID，也不要只用正文哈希去合并不同时间说过的相同话。
2. `role` 保留真实说话者；不要把鲸鱼说的“你大概喜欢……”改成用户确认的偏好。真实角色不是 `user/assistant/tool/system` 之一时，先明确映射规则。
3. `occurred_at` 是原始发生时间，必须有时区。缺失或不确定时，先保留原始文件和缺失清单，人工确认，不能把今天冒充所有旧消息的日期。
4. 人设文件用 `category: persona`，引用资料用 `reference`，真实对话用 `conversation`。人设背景、虚构情节不应转换成真实共同经历。
5. 推荐按原始时间顺序写入；事实有效期使用原始时间，不使用导入日期。单条最长 200,000 字符；更长的内容需保留完整外部原件，并以稳定片段 ID 和来源位置拆分，不能静默截掉。

**当前没有 DeepSeek、ChatGPT、Claude 任意导出格式的一键适配器。** 必须先根据实际导出结构转换到上述格式；保留字段映射和源消息 ID，才能核验转换是否完整。新增脚本负责校验和入库，不替你猜平台格式。

CLI 的 `memlikehuman import` 则是恢复 **MemLikeHuman 自身的版本化备份**，不能直接用于这个消息 JSONL 文件。

## 第三步：先离线保存全部原文

以下命令在本项目源码目录执行。需要完成 `uv sync --frozen`。将 `/PRIVATE/...` 替换成本机绝对路径，Windows 可使用 `C:/Users/YOU/...`。真实档案和导出文件不要放进公开仓库。

初始化专用档案：

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale init
```

先做全文件校验，不写入数据库、不调用模型：

```sh
uv run python examples/import_chat_history.py /PRIVATE/history.events.jsonl \
  --data-dir /PRIVATE/whale-memory --persona whale --project companionship --dry-run
```

确认消息总数、唯一 ID 数与转换清单相符，再实际导入：

```sh
uv run python examples/import_chat_history.py /PRIVATE/history.events.jsonl \
  --data-dir /PRIVATE/whale-memory --persona whale --project companionship

uv run memlikehuman --data-dir /PRIVATE/whale-memory doctor
uv run memlikehuman --data-dir /PRIVATE/whale-memory backup /PRIVATE/whale-before-extraction.sqlite3
```

这个脚本即使在数据目录已配置模型时也**不调用 API**，只保存原文。它会先完整校验输入，再逐条提交；错误格式或文件内同 ID 内容冲突会在写入前被拒绝。若途中遇到已有数据库的 ID 冲突或进程中断，之前提交的记录仍保留；检查并解决冲突后用同一份源 ID 重跑，相同事件会去重。全文件导入不是一个大事务，`dry-run` 也不检查与已有数据库的冲突。

导入后的 `pending` 表示原文已经持久化，尚未完成提炼。不要把它理解成“没存成功”。也不应把 `doctor` 的全库计数直接当作本次导入数量：本次数量看脚本的 `inserted` 和 `duplicates`。

## 第四步：分批提炼，先试 20 条

复制并编辑 [提炼配置示例](../examples/config.json)，选择实际可用的模型。在运行命令的环境里设置相应 API key，再执行：

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory config --file /PRIVATE/extraction-config.json
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale --project companionship retry --limit 20
```

先检查这 20 条的结果：角色是否正确、原文片段是否匹配、推测有没有变成事实、虚构情节有没有变成共同经历。确认符合预期后再分批：

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale --project companionship retry --limit 100
```

每次处理当前分区内最多 100 条待提炼事件，**不是一次让模型阅读全部 100 天**。检查输出后继续下一批；出现 API 或证据校验错误时先处理原因，不要无限循环重试。失败项保留为 pending；若队列前部反复失败，它们会占用后续批次，需要先解决。

当前提炼以单个事件为单位。“我也是”“就按昨天说的做”等依赖前文的表达，可能不能单靠这一条准确理解。这部分应结合原文人工核对，使用 `derive` 提交经过检查、带原文证据的提炼结果，或等待后续有上下文的提炼适配器；不能宣称当前自动提炼完整理解了每段关系。

**时间和费用取决于消息数、消息长度和提供商。** 先对 20 条实际测量耗时与用量，再估算全量。此前的毫秒级基准仅指本地检索，不是全量提炼速度。使用云端提炼时，当前事件会发给该提供商；不希望外发时，可使用本地兼容 API，或保持未配置并通过人工 `derive` 整理，原文查询仍可用。

## 第五步：单独保存人格与当前交接

不要让 100 天记录自动覆盖核心人格。将你有权使用的鲸鱼人设整理为 `name/traits/values/style/boundaries` 格式，人工确认后保存：

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale persona --file /PRIVATE/whale-persona.json
```

[原创简短示例](../examples/whale-memory-persona.json)可作格式参考，但不含完整的社区鲸鱼人设。

“100 天里聊过什么”和“现在还有什么没完成”分别处理。由用户核对当前任务，写成 TaskState JSON。例如：

```json
{"goal":"继续开发个人网站","completed":["确认首页内容"],"pending":["完成移动端布局"],"constraints":["先测试再提交"],"next_step":"检查手机宽度下的导航"}
```

接着保存交接：

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale --project companionship \
  checkpoint /PRIVATE/current-task.json --covered-event ORIGINAL_EVENT_ID --session ORIGINAL_SESSION_ID
```

这里两个 ID 必须对应已导入且属于同一会话的事件。checkpoint 是一份人工核实的当前工作状态，不意味着跨会话的全部历史已被自动总结或验证。

## 第六步：验证真的迁移成功

先列出至少 10 个你知道答案的问题，保留对应原文位置，覆盖：早期经历、最近变化、共同约定、未确认的推测、尚未完成的工作。不要只测“记住这个新暗号”，因为那验证不了 100 天旧历史。

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale --project companionship recall '先测试再提交'
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale --project companionship read 'dsh:profile-a:session-01:msg-001'
uv run memlikehuman --data-dir /PRIVATE/whale-memory --persona whale --project companionship resume --query '接下来要做什么' --budget 8000
```

上面的示例 ID 仅存在于你导入了本文合成例子的情况下；真实使用时替换为真实事件 ID。历史问题可用 `recall --as-of 带时区的时间` 或 `--history` 核验。

记录每题的预期答案、实际召回 ID、来源是否正确、有没有凭空补细节。原文完整入库与语义提炼正确是两项不同的验收，数据库 `integrity: ok` 不能证明模型理解正确。

再按 [Harness 指南](deepseek-harness.zh-CN.md)接入：保持同一数据目录，所有工具调用明确传 `persona_id="whale"`、`project_id="companionship"`。新建空会话，先 `session_resume`，再提问；需要具体往事时 `memory_recall → memory_read`。恢复只带当前所需的内容，完整日记继续留在本地。

100 多天不一定触发淡忘：默认从 180 天起才将旧经历呈现为概览。年龄按消息原始时间算，不从迁移当天重新计算；事实、偏好和约定依然保持详细。

## 第七步：以后增量保存并备份

- 新对话继续遵守 `memory_record → checkpoint → resume` 的调用约定。通用 MCP 不能强制模型每次都调用，应检查实际工具记录。
- 再导出同一历史时，保留同一消息 ID；新增消息使用新 ID，避免重建全部记忆。
- 迁移验收后再做一份备份，并在重大更正或迁移前保留新快照。备份包含私人聊天，放在私人目录。

```sh
uv run memlikehuman --data-dir /PRIVATE/whale-memory backup /PRIVATE/whale-after-migration.sqlite3
uv run memlikehuman --data-dir /PRIVATE/whale-memory export /PRIVATE/whale-after-migration.jsonl
```

这个最后导出的 JSONL 是 MemLikeHuman 备份，与最开始的逐条聊天 JSONL 格式不同。恢复到新的空目录，用 `restore`；模型提供商配置和密钥不会随备份导出，需另行配置。

## 如果继续用不支持 MCP 的聊天框

当前不能靠安装本服务让任意官网聊天框自动读写本地 SQLite。可以在本地运行 `resume`，把返回的 `context` 手动粘入新会话；后续的查询、记录和交接也需要手动执行。它只是有限、按预算选择的恢复包，不是全量记忆，也不会自动更新。一键 Markdown 记忆包仍属于后续改进。
