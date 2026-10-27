# DSH 插件安装、升级与卸载

MemLikeHuman 为 DeepSeek Harness 保存可见对话与压缩交接，并通过 MCP 提供检索和恢复。能力分类：**记忆与上下文**。独立社区项目，Apache-2.0，与 DeepSeek 无官方隶属关系。

## 运行要求与重要变更

- 插件适配 Harness **0.2.1-rc.3**，通过 `engines.dsh` 限定版本。JS 适配器要求 Node 22+；Harness 自身的 Node 要求以其发行版为准。
- Python **3.11+**、SQLite FTS5、uv；Python 核心与 npm 插件分别安装。npm 包不会自动下载 Python 或执行安装脚本。
- 支持 `web` / `desktop` profile 配置；实际验证范围见 [发布验证记录](release-verification.md)。
- 自动捕获插件在所选预设现有的 **BasicCompactionEngine 实例**上安装可卸载的摘要写入保护，保留原压缩阈值和模型配置。其他压缩器不受支持；重复安装保护会报错。
- 数据库升级为 **v3**；旧版本程序不能打开升级后的库。已有用户先用旧版 `backup` 命令备份，再升级或运行配置命令。

## 1. 安装 Python 核心

```sh
git clone https://github.com/xeonphi1/memlikehuman.git
cd memlikehuman
uv sync --frozen
```

记住该目录的绝对路径。macOS/Linux 程序在 `.venv/bin/memlikehuman`，Windows 在 `.venv/Scripts/memlikehuman.exe`。安装包不内置鲸鱼预设；若使用默认 `preset=whale`，需自行安装对应预设，或在配置时选择已有 preset ID。

## 2. 安装 DSH bundle

当前版本采用 GitHub 源码分发，未发布 npm。使用仓库源码安装：

```sh
dsh plugin --profile web add github:xeonphi1/memlikehuman
```

包使用原生 `.mjs`，不需要构建或授权 `prepare` 脚本。也可在仓库中执行 `npm pack --ignore-scripts` 后安装生成的 `.tgz`（源码安装需要本次改动已推送）：

```sh
dsh plugin --profile web add /ABSOLUTE/PATH/memlikehuman-harness-host-0.2.0.tgz
```

当前申请 **DSH 网站收录**。应用内插件中心要求 npm 包，因此本次不提供市场内的一键安装；从网站打开 GitHub 后按以上源码命令安装。未来如发布 npm，会另行更新说明。

Desktop 用户将 `web` 换成 `desktop`。使用已经正常运行的 profile；不要为了装插件重置现有 profile。

## 3. 一次性配置

在 Python 源码仓库根目录执行：

```sh
node plugin/setup.mjs --command /ABSOLUTE/PATH/memlikehuman/.venv/bin/memlikehuman --data-dir /ABSOLUTE/PATH/private/memory --persona whale --project companionship --preset whale
```

安装 bundle 后也可从所用 profile 的包环境运行其命令：

```sh
dsh plugin --profile web exec memlikehuman-setup --command /ABSOLUTE/PATH/memlikehuman/.venv/bin/memlikehuman --data-dir /ABSOLUTE/PATH/private/memory
```

Windows 替换为 `.venv/Scripts/memlikehuman.exe`。包含空格的路径用引号括起。配置命令检查 Python 是否提供 `host-ingest`，运行 `doctor`，成功后原子保存配置；失败不覆盖旧配置。

配置文件为 `~/.dsh/memlikehuman.json`，设置了 `DSH_HOME` 时则为 `$DSH_HOME/memlikehuman.json`。命令与 Harness 必须使用同一 `DSH_HOME`。`instanceId` 首次随机生成，重复配置保持不变；不同 Harness 安装不要复制同一 ID。此配置默认供该 DSH_HOME 下所有 profile 使用；两套独立运行实例应使用不同 DSH_HOME。

重启 Harness。bundle 自动加载捕获插件和 `memlikehuman` MCP 服务。未配置时不修改现有压缩器并警告，自动捕获和 MCP 均未启用；配置错误会明确报错。

## 从旧手动补丁升级

1. 备份数据库和用户 `cordis.patch.yml`。
2. 删除旧的 MemLikeHuman `compaction-basic` 覆盖行，以及旧 `memory-memlikehuman` MCP 插入块；保留鲸鱼等其他插件。用户补丁优先于 bundle，不清理会继续加载旧代码或造成重复实例。
3. 若旧手动替换行包含自定义压缩配置，将其恢复到目标预设原有的 BasicCompactionEngine 配置中；bundle 复用该实例，不覆盖阈值或摘要模型。
4. `dataDir`、`persona`、`project`、`instanceId` 必须沿用旧自动捕获配置；首次运行 setup 时用 `--instance-id OLD_ID`，避免历史重放产生副本。
5. 若要不同 profile 独立配置，可在各自用户补丁中覆盖 `memlikehuman-capture` 和 `memory-memlikehuman` 两行，分别保留包名并设置相同的 `config.configFile` 绝对路径。

## 验收与调用约定

先运行 `dsh --profile web --dump-config`，确认包含此 bundle 的层及两个插件入口。随后检查真实会话：

1. 在所选预设说出合成暗号“蓝鲸茶杯-731”，确认本地 `recall` 可查到原文。
2. 重启并继续对话，确认历史未重复写入。
3. 手动 `/compact` 后通过 `resume` 和 `read` 检查交接摘要与原文。
4. 新会话调用 `session_resume`，参数为配置中的 `persona_id`、`project_id`；旧事实用 `memory_recall` / `memory_read`。

自动捕获模式下不要再要求模型逐条调用 `memory_record`，否则可能重复记录。插件不会强制模型在新会话中调用恢复工具；仍需在宿主指令中声明这一约定。附件、隐藏推理和工具输出不在自动捕获范围。

## 权限与外部服务

启动本地 Python 子进程、读取选定预设的可见会话文本、写入私人 SQLite 数据目录；本地数据为明文。自动捕获不调用模型 API。压缩摘要仍使用 Harness 原有摘要模型；可选 Python 提炼/embedding 会把相关内容发给用户配置的服务商。MCP 显式转发 `MEMLIKEHUMAN_API_KEY`，配置文件不保存密钥。

## 升级与卸载

升级前备份数据，核对目标 Harness 版本；更新 Python checkout 后 `uv sync --frozen`，再安装目标 npm 版本或新 tarball，最后重启。不要无验证地放宽 `engines.dsh`。

```sh
dsh plugin --profile web remove memlikehuman-harness-host
```

重启后 bundle 层移除，原压缩器的摘要方法恢复，阈值和模型配置不变。若仍保留旧手动覆盖，需要一并移除对应行。卸载**不会删除** Python 环境、`memlikehuman.json` 或记忆库。降级 Python 前应恢复旧版本备份到新目录，不能用旧程序直接读取 v3 库。
