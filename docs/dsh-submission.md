# 市场提交材料

标题：`[插件提交] xeonphi1/memlikehuman — 为 Harness 保存本地对话记忆与压缩交接`

### 仓库地址
https://github.com/xeonphi1/memlikehuman

### 一句话价值
自动保存所选预设的可见对话，在压缩前后等待本地持久化，并通过 MCP 为新会话提供有来源的检索和恢复。

### 能力分类
记忆与上下文

### 安装命令
```sh
dsh plugin --profile web add github:xeonphi1/memlikehuman
```
Python 核心需先单独安装，并运行一次 `memlikehuman-setup`。完整步骤见仓库 `docs/dsh-install.md`。npm 包名为 `memlikehuman-harness-host`，本次选择 GitHub 源码分发，暂不发布 npm；当前申请网站源码插件收录，不申请应用内插件中心一键安装。

### 兼容与运行要求
Harness 0.2.1-rc.3，适配器 Node 22+，Python 3.11+ 与 SQLite FTS5。支持 web/desktop 配置；实际宿主测试为 macOS Web 后端，内置 standard 预设与合成会话。新会话恢复仍需宿主调用约定。

### 许可证
Apache-2.0

### 截图 / 演示
仓库 `docs/release-verification.md`：真实 Harness 自动捕获 → SQLite → MCP 检索结果，以及可复现的无付费 API 测试夹具。

### 补充说明
启动本地 Python 子进程，写入用户指定的明文 SQLite 目录。自动捕获不调用外部模型；Harness 压缩模型及用户可选的提炼/embedding 服务按配置使用。数据库 v3 升级前需备份。仅保护官方 BasicCompactionEngine；支持卸载恢复其原方法。独立社区项目，无官方隶属关系。

### 提交前自查
- [x] 仓库已公开
- [x] 已添加 GitHub topic：dsh-plugin
- [x] README 包含安装命令
- [x] 插件导出 apply(ctx) 模块
- [x] 仓库根目录包含 package.json
