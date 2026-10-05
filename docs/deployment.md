# Deployment / 部署

## Configuration

| Variable | Default | Purpose / 用途 |
| --- | --- | --- |
| `PEAT_HOST` | `127.0.0.1` (Docker: `0.0.0.0`) | Bind address / 监听地址 |
| `PEAT_PORT` | `8787` | HTTP port / HTTP 端口 |
| `PEAT_DATA_DIR` | `./data` (Docker: `/data`) | Database, encryption key and runtime / 数据与运行环境 |
| `PEAT_SECURE_COOKIES` | `false` | Use `true` behind HTTPS / HTTPS 部署设为 true |
| `PEAT_ORIGINS` | Local 8787/5173 origins | Explicit allowed browser origins, comma-separated / 允许的浏览器来源 |
| `PEAT_REGISTRATION_OPEN` | `true` | Allow registration after bootstrap / 首次初始化后允许注册 |
| `PEAT_CONSOLE_ENABLED` | `true` | Admin command console / 管理员命令行 |
| `PEAT_ENCRYPTION_KEY` | Generated on first run | Optional Fernet key override / 可选加密密钥覆盖 |
| `PEAT_LLM_ALLOWED_HOSTS` | Empty | Explicit local/private LLM hostnames / 本地或内网模型主机白名单 |

Source deployments read `.env` from the working directory. Compose interpolates the variables listed in `compose.yaml`. To supply a custom encryption key to Docker, add it as an environment variable through a local Compose override or your secret manager. Never place it in the Dockerfile or commit the override.

源码部署从工作目录读取 `.env`。Compose 只传递 `compose.yaml` 中明确列出的变量。需要向容器提供自定义加密密钥时，使用本地 Compose 覆盖文件或密钥管理工具；不要写入 Dockerfile 或提交带密钥的文件。

## Remote access

The default port binds to loopback. A reverse proxy can terminate HTTPS and forward to `127.0.0.1:8787`. Set the public origin, enable secure cookies, and keep the administrator account for the instance operator. Do not forward a public port until the initial administrator is created.

默认仅监听本机。远程部署可由反向代理提供 HTTPS，并转发至 `127.0.0.1:8787`。填写公开来源地址、启用 secure cookies，先创建管理员再开放访问。管理员控制台的权限等同于应用服务账户。

Example Caddy configuration:

```caddyfile
peat.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

```dotenv
PEAT_ORIGINS=https://peat.example.com
PEAT_SECURE_COOKIES=true
PEAT_REGISTRATION_OPEN=false
```

For LAN access without a proxy, explicitly change the Compose port binding and `PEAT_ORIGINS`. Server time should be synchronized; timestamps are UTC and the browser renders local dates. The SQLite application runs as a single process; multiple Uvicorn workers would duplicate scheduled polling and split job state.

局域网直接访问需主动修改端口绑定和 `PEAT_ORIGINS`。服务器应同步时间；记录使用 UTC，浏览器按当地时间显示。应用使用单进程，多 Uvicorn worker 会重复启动轮询并分散任务状态。

## Backups

Stop the service before copying the data directory or taking a volume snapshot. Preserve `peat.sqlite3`, `master.key`, `codex-shared.json`, shared and legacy user Codex directories, and runtime override markers. With an externally provided encryption key, back it up in your secret manager as well. Restoring a database without its key cannot recover API credentials.

停止服务后复制完整数据目录或创建数据卷快照。保留 `peat.sqlite3`、`master.key`、`codex-shared.json`、共享及历史用户 Codex 目录和运行版本标记。外部提供的加密密钥还需单独备份；仅恢复数据库无法解密 API 凭据。

## Dependency maintenance

Settings → Runtime can install an exact Codex or `exchange-calendars` version. Codex installs into `data/runtime/codex-versions/<version>` and switches only after a version check. Calendar dependencies install into `data/runtime/calendar-versions/<version>` and activate after restart. Installing a previously used version provides a rollback. Application dependencies remain locked by release.

设置 → 运行环境可安装指定 Codex 或 `exchange-calendars` 版本。Codex 先安装到独立版本目录，通过版本检查再切换；日历依赖在重启后生效。再次选择旧版本即可回退。应用其余依赖随 release 锁定。

## Codex

The image includes Codex `0.155.1` by default; the build argument `CODEX_VERSION` selects another exact version. An administrator completes Settings → Start device login once and all Peat users can select Codex models for research. Only administrators can log in or disconnect the shared account. Device authorization is completed by the account owner on the official login page.

默认镜像包含 Codex `0.155.1`，可通过构建参数 `CODEX_VERSION` 选择版本。管理员在“设置 → 开始设备登录”完成一次授权后，所有 Peat 用户均可选择 Codex 模型进行研究；登录和退出仅限管理员。设备授权由账户所有者在官方页面完成。

`CODEX_HOME` points to the directory recorded in `data/codex-shared.json`. On first use after upgrade, Peat adopts an existing active administrator's login under `users/<id>/codex` without copying tokens. New device logins use `shared/codex`. Keep both the marker and its selected directory when backing up. Signing out does not fall back to another stored account. Credentials are never returned to the browser. `HOME`, temporary files and research workspaces remain per user; inference is ephemeral, ignores user configuration and disables tools. Research enters through stdin with no inherited host API keys or trading credentials.

`CODEX_HOME` 指向 `data/codex-shared.json` 记录的目录。升级后首次使用会沿用活跃管理员在 `users/<id>/codex` 中的登录状态，不复制令牌；新的设备登录使用 `shared/codex`。备份需保留该标记及其指向的目录。退出后不会自动切换到另一历史账户。凭据不返回浏览器；`HOME`、临时文件和研究工作目录仍按用户独立。研究使用临时会话、忽略用户配置并禁用工具；上下文从 stdin 传入，不继承宿主 API Key 或传入交易凭据。

## Background research / 后台研究

Generation runs independently of browser connections. There is no Peat timeout on the model request or Codex inference; the global task bar provides a manual Stop button. Network limits for model discovery and news acquisition remain separate. A service restart interrupts active work and keeps its status for the next visit; users can generate again after restart. Keep one application process per data directory.

生成任务独立于浏览器连接运行。Peat 不对模型请求或 Codex 推理设置超时，全局任务栏提供手动中止。模型列表和新闻获取各自保留网络时限。服务重启会中断正在运行的任务，并保留状态供下次访问查看；重启后可重新生成。每个数据目录运行一个应用进程。

## Administrator console / 管理员控制台

The Web console is separate from AI research: authenticated administrators can intentionally execute server commands, with a 60-second timeout and a bounded output buffer. It is not a PTY/full-screen terminal. Set `PEAT_CONSOLE_ENABLED=false` to disable it for a hosted deployment.

Web 控制台支持管理员执行服务端命令，单次 60 秒并限制输出大小，不提供 PTY 全屏交互。托管部署可用 `PEAT_CONSOLE_ENABLED=false` 关闭。
