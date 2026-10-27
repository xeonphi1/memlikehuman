# DeepSeek Harness 自动捕获与压缩交接

此插件将选定预设的可见用户文本和助手回复自动存入 MemLikeHuman，压缩前等待本地写入，摘要生成后再次保存交接，然后才允许宿主替换上下文。无需模型主动调用 `memory_record`，捕获过程不调用提炼 API。人格编辑、检索、恢复仍使用原有 CLI / MCP。

## 安装

使用 [DSH bundle 安装、升级与卸载指南](dsh-install.md)。适配 Harness **0.2.1-rc.3**、Node 22+、Python 3.11+；Harness 本身的运行环境要求以发行版为准。插件使用 `agent/created`、`agentPresets.serviceFor` 找到所选预设的独立压缩器，在其 `summarize` 实例方法上安装写入保护，卸载时恢复。保留原压缩策略和摘要模型；不支持其他类型的压缩器。

旧版将 `compaction-basic` 行的 `name` 改成适配器路径的补丁不可继续使用：该字段是匹配条件，且 Web 预设内的压缩器具有独立作用域。请按升级指南清理旧覆盖，改为安装 bundle。不要同时加载两套自动捕获实例。

安装此插件后，调整原来的宿主指令：不要再逐条用 `memory_record` 记录同样的对话；新会话仍调用 `session_resume(persona_id="whale", project_id="companionship")`，不指定旧 session。需要旧事时调用 `memory_recall` / `memory_read`。人格并未因启用插件而被修改。

## 保存了什么

- 仅 `source.kind=user` 的用户文本，以及最终/中断时已组装的助手可见文本；保留宿主事件时间、角色和可追溯事件序号。
- 每个文本块分片保留原文；记录 ID 由分区、宿主实例、会话和事件位置生成，重试不会重复产生记录。
- 不把系统提示词、隐藏推理、工具参数或宿主注入的 user-role 摘要误记为用户说过的话。本版不复制图片/音频二进制，也不采集工具结果；附件仍需单独保存或作为线索手动提交。
- 在本地 SQLite 中保存读取位置；JSON/JSONL 导出及 SQLite 备份包含该位置。删除记忆后重启，不会因为回放原日志而自动恢复旧记录。另换 `instanceId` 或重新导入原始日志属于一次新的导入，可能产生副本。
- 原文状态为 `pending`，可以立即通过原文检索读取。需要事实/偏好/概览时，另外运行 `retry --limit 20` 等提炼命令；本插件不在聊天关键路径上调用云端提炼或 embedding。

## 压缩时序与失败行为

```mermaid
sequenceDiagram
    participant H as Harness
    participant P as 宿主插件
    participant D as 本地 SQLite
    H->>P: 可见消息事件
    P->>D: 增量原文（250ms 合并触发）
    H->>P: 开始压缩摘要
    P->>D: 等待原文落盘 + 保存交接位置
    D-->>P: 确认
    P->>H: 调用原有摘要模型
    H-->>P: 压缩摘要
    P->>D: 摘要作为助手参考资料 + 交接指针
    D-->>P: 确认
    P-->>H: 允许替换上下文
```

自动压力压缩、上下文溢出重试、手动 `/compact` 和区域压缩，都经过原压缩器的摘要入口。写入超时、磁盘故障、桥接失败时抛错，本次压缩不进入上下文替换。修复后重试即可。普通消息监听器失败时显示警告，已提交宿主日志不会因此消失；下一次 flush / 重启从已确认位置重试。

首次接入很长历史可能需要较长补录时间。每次最多扫描 50 个宿主事件，不随每一轮重复扫描全库。它有 Python 子进程启动与 SQLite 写入开销，**不能套用 README 中纯检索的毫秒基准**。宿主日志在本插件确认前也尚未持久化、且进程遭强杀的极小窗口，仍依赖 Harness 自身的日志恢复；本插件不能承诺零丢失。

压缩前若已有结构化任务状态，会保留它；没有时保存“待确认当前任务”的原文指针，不猜测任务完成情况。摘要保存为 assistant/reference，交接指向摘要记录，并标注应核对原文。摘要覆盖宿主选定的压缩区间，不保证概括所有保留尾部。原结构化交接历史仍在导出包中。总结失败但原文已保存，不会回滚原文。

## 验收与排错

1. 用合成对话说“我以前住上海，现在住杭州；下一步整理照片”。等待该轮结束。
2. 使用相同数据目录执行 `memlikehuman --data-dir /PRIVATE/memory --persona whale --project companionship recall 杭州`，应能找到原文；不需要先运行提炼 API。
3. 正常重启 Harness，继续一条新消息，再查原文，应只有一次原始记录。
4. 手动 `/compact`（宿主需要有足够可压缩历史），通过 `resume` 查看交接，按其 ID 用 `read` 阅读助手摘要。
5. 在测试数据目录中故意配置不存在的桥接命令，执行压缩应报错；恢复命令后可重试。不要使用自己的唯一记忆库做破坏性试验。
6. 换模型、新建鲸鱼会话，通过 MCP `session_resume` 读取同一份记忆，再验证来源及下一步。

自动化测试覆盖真实 Python 子进程与 SQLite、官方 npm Session 消息格式、官方 BasicCompactionEngine 摘要方法、失败阻止压缩、重启增量、跨预设隔离、删除与导出恢复游标。安装与启动验证见 [发布验证记录](release-verification.md)；付费模型效果未验证。

适配器目前使用官方仍提供的 `snapshotEvents(from, to)` 范围读取接口；上游将其标记为 deprecated。升级 Harness 前运行插件测试并检查接口，不要无验证地修改依赖版本。

## 开发验证

```sh
# 仓库根目录
uv run pytest -q
# 插件目录（先 npm ci）
MLH_COMMAND=/ABSOLUTE/PATH/memlikehuman/.venv/bin/memlikehuman npm test
```

参考：[官方会话事件接口](https://github.com/deepseek-ai/deepseek-harness/blob/22ddee3792402c3e70ec5f86a63c3e3e895a2f60/packages/core/session/src/index.ts)、[官方压缩器扩展点](https://github.com/deepseek-ai/deepseek-harness/blob/22ddee3792402c3e70ec5f86a63c3e3e895a2f60/packages/compaction/compaction-basic/src/index.ts)。
