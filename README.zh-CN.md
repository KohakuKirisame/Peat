# <img src="frontend/public/peat-logo.png" width="48" alt="Peat 标志"> Peat

**连接你的持仓、市场和下一步值得关注的信息。**

可自主部署的投资研究助手，集成 Trading 212、本地新闻与可配置 AI。技术栈为 React + FastAPI + SQLite，不包含交易或下单功能。

[English](README.md) · [部署说明](docs/deployment.md) · [架构与数据](docs/architecture.md) · [AGPL-3.0](LICENSE)

## 功能

- PC 与手机响应式界面；中英文；默认星空深色主题，支持浅色和跟随系统；自定义强调色。
- 用户名密码注册；首个账户为超级管理员；支持编辑用户名称、角色、启用状态和密码。
- Trading 212 Invest/Stocks ISA 账户总价值、当前持仓成本、现金、已实现/未实现收益、持仓、成交、股息及资金流水；区分真实与模拟账户。
- 交互式 K 线：1/5/15 分钟、小时、日、周、月；时间范围、悬停 OHLC、成交量和历史浏览。每位用户可保存行情代码映射。
- 含假期、夏令时及午休的交易日历；美债 2/10/30 年期收益率、WTI/布伦特原油、天然气、黄金、白银和铂金。
- 持仓和关注列表公司的新闻与行业 RSS 摘要，纯文字展示、本地存储、数量/天数上限及手动清理。
- OpenAI 兼容 Chat Completions API 与本地 Codex CLI；读取模型列表、自填 API 模型 ID、选择思考强度。
- 极度保守、保守、常规、激进、极度激进五档风格；通用与各档提示词可编辑、恢复默认；每份分析保存证据、提示词、模型和思考强度。
- Web 内 Codex 设备码登录，各用户登录目录独立；管理员命令行控制台与 Codex/交易日历依赖版本更新。
- API 凭据加密、密码哈希、Docker 持久化存储、CI 与多架构 Docker 发布流程。

## Docker 部署

需要 Docker Engine 与 Compose。镜像由版本标签工作流发布至 `ghcr.io/kohakukirisame/peat`，支持 `linux/amd64` 与 `linux/arm64`。

```sh
git clone https://github.com/KohakuKirisame/Peat.git
cd Peat
docker compose up -d
```

打开 **http://localhost:8787**，创建首个管理员账户。数据库、加密密钥、Codex 登录状态和依赖覆盖版本均保存在 `peat-data` 数据卷中。

从源码构建镜像：

```sh
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

更新应用：

```sh
docker compose pull
docker compose up -d
```

更新时保留数据卷。设置 → 运行环境中可安装指定 Codex 或交易日历版本。Codex 通过版本验证后立即切换；日历更新后执行 `docker compose restart peat`。Python/FastAPI 和前端随应用镜像更新。

## 源码部署

使用 **Python 3.13** 与 **Node.js 24 LTS**。Python 依赖与哈希锁定在 `requirements.lock`，前端依赖锁定在 `frontend/package-lock.json`。

Windows PowerShell：

```powershell
git clone https://github.com/KohakuKirisame/Peat.git
cd Peat
Copy-Item .env.example .env
.\scripts\start.ps1
```

Linux/macOS：

```sh
git clone https://github.com/KohakuKirisame/Peat.git
cd Peat
cp .env.example .env
sh scripts/start.sh
```

后续启动可激活虚拟环境后运行 `python -m peat`。源码部署可在设置中安装 Codex，也可使用机器上已安装的 `codex`。Docker 镜像已包含 Node、npm、Codex、Python、交易日历、Git 和 ripgrep。

## 首次配置

1. **账户：** 用户名 3–32 位，支持字母、数字与 `_.-`；密码 10–128 位。首个账户自动成为管理员。需要关闭后续注册时，设置 `PEAT_REGISTRATION_OPEN=false`。
2. **Trading 212：** 填写具备账户、持仓和历史读取权限的 API Key 与 API Secret，选择真实/模拟环境，然后在总览同步。API 支持 Invest 和 Stocks ISA。
3. **历史：** 账户流水按平台分页导入，每页最多 50 条。“读取更早历史”继续上次游标；界面显示历史覆盖是否完整。可导入英文列名的 Trading 212 CSV，分币种汇总入金、出金、股息和对账单已实现收益。
4. **新闻：** 添加公司和行业名称到关注列表，再获取新闻。Google News RSS 无需注册 API。达到保存上限时自动清理最旧记录。
5. **AI API：** 填写含 `/v1` 的接口地址与密钥。本地服务器需在 `PEAT_LLM_ALLOWED_HOSTS` 显式列出主机名，例如 `localhost,127.0.0.1,host.docker.internal`。
6. **Codex：** 在设置中开始设备登录，打开验证链接并输入一次性设备码。需要时在 ChatGPT 安全设置启用设备码登录。每位用户分别授权，应用不会导入宿主机已有凭据。
7. **研究：** 在智能研究中选择平台、模型、思考强度与策略等级。Codex 登录后刷新模型列表。可编辑通用及各策略提示词，保存后生成简报。本次分析会把持仓、行情和已保存新闻摘要发送给你选择的平台。

## 数据口径

“当前持仓成本”是未平仓头寸的成本基础，累计入金通过历史流水或对账单查看。账户汇总使用账户主币种，标的价格保留标的币种。CSV 按币种汇总、仅覆盖已导入记录，与实时账户汇总分别展示，避免重复计算。账户价值历史为 Peat 本地采集的快照，变化包含外部现金流。

Trading 212 默认每 60 秒轮询，可在设置调整，并受平台限流约束。Yahoo 报价与 K 线可能延迟或暂时不可用；使用行情源 OHLC，并未重构总回报价格。行情代码映射需核对标的、交易所和币种。美债收益率为日度公布数据。所有数据保留来源和时间；刷新失败时旧报价标记为过期。交易所状态根据常规交易日历计算，不反映临时停牌。

RSS 内容是发布方提供的标题与摘要，无法保证包含全文。每个新闻周期最多查询 30 个公司/行业主题。历史 AI 简报保存当时的证据与提示词；清理当前新闻不会改写历史分析。

## 开发与验证

```sh
python -m venv .venv
# 先激活虚拟环境
pip install --require-hashes -r requirements.lock
pip install pytest pytest-asyncio ruff
python -m pytest -q
ruff check peat tests
python scripts/check_secrets.py
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

测试覆盖注册和管理员权限、用户隔离、凭据加密、CSRF、币种处理、CSV 去重、新闻清理、假期/午休、K 线空缺及模型/思考强度/提示词留存。浏览器测试使用临时数据库，合成 K 线只存在于测试夹具。前端 `npm run dev` 会把 `/api` 代理至单独启动的 8787 端口后端。

## 数据存储与密钥

运行数据保存在 `PEAT_DATA_DIR`，默认 `./data`。API Key 使用 Fernet 加密，主密钥首次启动生成到 `data/master.key`，也可由部署者设置 `PEAT_ENCRYPTION_KEY`。密码使用 Argon2id，数据库只保存会话令牌的哈希。Codex 凭据由其自身保存在用户独立的私有运行目录。

停止 Peat 后备份**完整数据目录或数据卷**，包括主密钥。Git 忽略规则排除运行数据与凭据；Docker 构建上下文采用白名单，不会复制本地 `.env`、数据目录或 Codex 登录状态。CI 检查源码中的密钥模式及私有运行路径。测试数据和源码均不应包含你的真实密钥。

管理员控制台以 Peat 服务器的服务账户运行命令，供实例维护者使用；管理员属于可信运维角色。默认 Compose 仅绑定本机，使用非 root 用户且不挂载 Docker socket。远程访问请配置 HTTPS、secure cookies 与明确的来源地址，详见[部署说明](docs/deployment.md)。

## 许可与标志

Copyright © 2026 KohakuKirisame。采用 **GNU AGPL v3.0 only**。修改后的网络部署应按许可向使用者提供对应源码；依赖保留各自许可。

Peat 标志由内置图像生成工具创作，以艾雷岛泥煤为主题，采用深泥煤、海岸鼠尾草与盐白色。PNG 和完整生成提示词见[品牌说明](docs/brand.md)。

## 官方参考

- [Trading 212 API](https://docs.trading212.com/)
- [美国财政部 XML 收益率数据](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
- [Codex 登录](https://learn.chatgpt.com/docs/auth)与[模型发现](https://learn.chatgpt.com/docs/app-server#models)
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars)

Yahoo Finance 公共图表接口与 Google News RSS 是外部公共数据源，可用性及使用条件可能变化；代码中的数据源模块可替换。
