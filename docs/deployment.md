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

Stop the service before copying the data directory or taking a volume snapshot. Preserve `peat.sqlite3`, `master.key`, user Codex directories and runtime override markers. With an externally provided encryption key, back it up in your secret manager as well. Restoring a database without its key cannot recover API credentials.

停止服务后复制完整数据目录或创建数据卷快照。保留 `peat.sqlite3`、`master.key`、用户 Codex 目录和运行版本标记。外部提供的加密密钥还需单独备份；仅恢复数据库无法解密 API 凭据。

## Dependency maintenance

Settings → Runtime can install an exact Codex or `exchange-calendars` version. Codex installs into `data/runtime/codex-versions/<version>` and switches only after a version check. Calendar dependencies install into `data/runtime/calendar-versions/<version>` and activate after restart. Installing a previously used version provides a rollback. Application dependencies remain locked by release.

设置 → 运行环境可安装指定 Codex 或 `exchange-calendars` 版本。Codex 先安装到独立版本目录，通过版本检查再切换；日历依赖在重启后生效。再次选择旧版本即可回退。应用其余依赖随 release 锁定。

## Codex

The image includes Codex `0.155.1` by default; the build argument `CODEX_VERSION` selects another exact version. Peat executes device login and model discovery under each user's `CODEX_HOME`. It passes research context through stdin, avoids inherited API key environment variables, disables agent tools and does not pass trading credentials to the model. Device authorization itself must be completed by the account owner in the official login page.

默认镜像包含 Codex `0.155.1`，可通过构建参数 `CODEX_VERSION` 选择版本。设备登录与模型发现使用用户独立的 `CODEX_HOME`；研究上下文从 stdin 传入，屏蔽宿主 API Key 环境变量并禁用 agent 工具，交易凭据不会发送给模型。设备授权由账户所有者在官方页面完成。

The Web console is separate from AI research: authenticated administrators can intentionally execute server commands, with a 60-second timeout and a bounded output buffer. It is not a PTY/full-screen terminal. Set `PEAT_CONSOLE_ENABLED=false` to disable it for a hosted deployment.

Web 控制台支持管理员执行服务端命令，单次 60 秒并限制输出大小，不提供 PTY 全屏交互。托管部署可用 `PEAT_CONSOLE_ENABLED=false` 关闭。
