# DSH bundle 发布验证记录

验证日期：2026-10-27。对象：`memlikehuman-harness-host@0.2.0` + Python 核心 0.2.0。

环境：macOS、本机 Node 25.9.0，npm 安装的官方 `@deepseek-ai/dsh@0.2.1-rc.3`。使用全新的临时 `DSH_HOME` 和合成记忆目录，没有修改用户日常 Harness 配置，没有调用付费模型。

## 已完成

| 验证 | 结果 |
|---|---|
| Python 完整测试 | 77 项通过 |
| 原宿主适配器测试 | 8 项通过，包含真实 Python 子进程与官方 Cordis/Session/BasicCompactionEngine |
| bundle 配置及生命周期测试 | 配置失败不覆盖旧文件、稳定实例 ID、未配置不修改压缩器、隔离压缩器保护、失败阻止摘要、卸载恢复 |
| npm tarball 检查 | 发布白名单不包含数据库、密钥、node_modules 或测试文件；无需安装时构建脚本 |
| 真实 DSH CLI 安装 | 临时 web profile 安装 tarball 成功，bundle 自动加入组合 |
| 配置层加载 | `--dump-config` 出现 `memlikehuman-capture` / `memory-memlikehuman`，没有 name mismatch |
| 从已安装包运行 setup | 成功检查 Python 并保存临时配置 |
| 真实 Harness Web 后端启动 | 在本机随机端口成功启动 |
| 真实 preset 作用域 | 创建内置 standard 预设的合成 Agent，找到并保护其隔离 BasicCompactionEngine |
| 自动捕获 → SQLite → MCP | 写入“合成验收暗号：蓝鲸茶杯-731”，等待 session flush，经真实 MCP `memory_recall` 读回同一暗号 |
| 卸载 | CLI remove 移除 bundle 层；临时配置、Python 环境及记忆库保留 |

真实运行的核心断言（测试夹具见 `scripts/dsh-release-smoke.mjs`）：

```text
isolatedPresetGuard: true
mcpToolRegistered: true
MCP memory_recall contains: 蓝鲸茶杯-731
```

## 复现

```sh
uv sync --frozen --group dev
npm ci --ignore-scripts
npm --prefix integrations/deepseek-harness ci --ignore-scripts
npm test
uv run pytest -q
npm pack --ignore-scripts
```

完整宿主复测请使用独立临时 `DSH_HOME`，安装 tarball，运行 setup（`--preset standard --persona whale --project companionship`），再通过 `--patch` 插入 `scripts/dsh-release-smoke.mjs` 的绝对路径。设置 `MLH_SMOKE_REPORT` 为临时 JSON 输出路径；以 `dsh --profile web --patch /path/smoke.patch.yml --no-open --port 0` 启动。夹具会创建合成会话，验证压缩器保护、真实 MCP 注册与检索，并写出结果。测试结束停止宿主，使用 CLI remove 检查卸载。

## 明确未验证

没有进行人工浏览器界面操作、鲸鱼社区预设完整联调或真实付费模型跨模型效果验收。压缩写入顺序与失败阻断通过真实官方摘要类和模拟模型验证，不将其称为付费模型端到端测试。Windows/Linux 的完整宿主安装仍需分别实测；Python CI 已覆盖三个系统。

插件适配已发布的 0.2.1-rc.3 API；上游源码主分支可能包含同版本尚未发布的 API，不能据此扩大兼容承诺。`snapshotEvents` 范围读取为上游已弃用接口，升级宿主前应重新验证。
