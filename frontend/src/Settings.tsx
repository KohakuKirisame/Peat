import { useEffect, useState } from "react";
import {
  Check,
  CheckCircle2,
  Circle,
  Code2,
  Download,
  ExternalLink,
  KeyRound,
  LogOut,
  Monitor,
  Moon,
  RefreshCw,
  Save,
  Sun,
  Users,
} from "lucide-react";
import {
  api,
  date,
  del,
  post,
  put,
  useAction,
  useApp,
  useResource,
} from "./api";
import type { Settings as Preferences } from "./api";
import { Button, External, Loading, Panel, ResourceError, Tag } from "./ui";

export function JobOutput({
  id,
  onDone,
}: {
  id: string | null;
  onDone?: () => void;
}) {
  const { t } = useApp(),
    [done, setDone] = useState(false),
    r = useResource(id ? "/jobs/" + id : null, done ? 0 : 1500);
  useEffect(() => setDone(false), [id]);
  useEffect(() => {
    if (r.data?.status && r.data.status !== "running") {
      setDone(true);
      onDone?.();
    }
  }, [r.data?.status]);
  if (!id) return null;
  if (r.error) return <ResourceError error={r.error} retry={r.reload} />;
  return (
    <div className="job-output">
      <Tag
        tone={
          r.data?.status === "failed"
            ? "amber"
            : r.data?.status === "completed"
              ? "green"
              : ""
        }
      >
        {r.data?.status === "running"
          ? t("Running", "运行中")
          : r.data?.status === "completed"
            ? t("Completed", "已完成")
            : t("Failed", "失败")}
      </Tag>
      {r.data?.output && <pre>{r.data.output}</pre>}
    </div>
  );
}

export default function Settings() {
  const { t, user, saveSettings, notify } = useApp();
  const [s, setS] = useState<Preferences>(user.settings);
  const connections = useResource("/connections"),
    codex = useResource("/codex/status"),
    action = useAction();
  const [broker, setBroker] = useState({
      api_key: "",
      api_secret: "",
      environment: "live",
    }),
    [llm, setLlm] = useState({
      api_key: "",
      base_url: "https://api.openai.com/v1",
    });
  const [loginJob, setLoginJob] = useState<string | null>(null),
    login = useResource(loginJob ? "/jobs/" + loginJob : null, 1500);
  useEffect(() => {
    setS(user.settings);
  }, [user.settings]);
  useEffect(() => {
    if (connections.data) {
      setBroker((b) => ({
        ...b,
        environment: connections.data.trading212.environment,
      }));
      setLlm((l) => ({ ...l, base_url: connections.data.openai.base_url }));
    }
  }, [connections.data]);
  useEffect(() => {
    if (login.data?.status === "completed") {
      codex.reload();
      setLoginJob(null);
      notify(t("Codex connected", "Codex 已连接"));
    }
  }, [login.data?.status]);
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("MAKE PEAT YOURS", "让 PEAT 适合你的习惯")}
          </div>
          <h1>{t("Settings", "设置")}</h1>
          <p>
            {t(
              "Your workspace, connections and preferences.",
              "管理工作台、连接和个人偏好。",
            )}
          </p>
        </div>
      </div>
      <div className="settings-grid">
        <div className="main-column">
          <Panel
            title={t("Connections", "平台连接")}
            sub={t(
              "Credentials are encrypted in your local database.",
              "凭据加密保存在本地数据库。",
            )}
          >
            <div className="connection-block">
              <div className="connection-title">
                <div className="provider-logo t212">212</div>
                <div>
                  <h3>Trading 212</h3>
                  <p>Invest / Stocks ISA</p>
                </div>
                <Tag
                  tone={connections.data?.trading212.configured ? "green" : ""}
                >
                  {connections.data?.trading212.configured
                    ? t("Configured", "已配置")
                    : t("Not connected", "未连接")}
                </Tag>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void action.run(
                    async () => {
                      await put("/connections/trading212", broker);
                      setBroker({ ...broker, api_key: "", api_secret: "" });
                      connections.reload();
                    },
                    t("Connection saved", "连接已保存"),
                  );
                }}
              >
                <div className="form-grid">
                  <label>
                    API Key
                    <input
                      autoComplete="off"
                      type="password"
                      value={broker.api_key}
                      onChange={(e) =>
                        setBroker({ ...broker, api_key: e.target.value })
                      }
                      placeholder={
                        connections.data?.trading212.configured
                          ? t(
                              "Saved · leave blank to keep",
                              "已保存 · 留空保留",
                            )
                          : t("Enter API key", "输入 API Key")
                      }
                    />
                  </label>
                  <label>
                    API Secret
                    <input
                      autoComplete="off"
                      type="password"
                      value={broker.api_secret}
                      onChange={(e) =>
                        setBroker({ ...broker, api_secret: e.target.value })
                      }
                      placeholder={
                        connections.data?.trading212.configured
                          ? t(
                              "Saved · leave blank to keep",
                              "已保存 · 留空保留",
                            )
                          : t("Enter API secret", "输入 API Secret")
                      }
                    />
                  </label>
                  <label>
                    {t("Environment", "账户环境")}
                    <select
                      value={broker.environment}
                      onChange={(e) =>
                        setBroker({ ...broker, environment: e.target.value })
                      }
                    >
                      <option value="live">
                        {t("Live account", "真实账户")}
                      </option>
                      <option value="demo">
                        {t("Demo account", "模拟账户")}
                      </option>
                    </select>
                  </label>
                </div>
                <p className="field-hint">
                  {t(
                    "Create an API key with account, portfolio, history and pies:read permissions. Switching credentials clears cached account data.",
                    "请使用账户、持仓、历史及 pies:read 读取权限的 API Key。更换账户凭据会清除原账户的本地缓存。",
                  )}
                </p>
                <div className="settings-actions">
                  <External href="https://docs.trading212.com/">
                    {t("API reference", "API 文档")}
                  </External>
                  <div className="button-row">
                    {connections.data?.trading212.configured && (
                      <button
                        type="button"
                        className="text-button danger"
                        onClick={() => {
                          if (
                            window.confirm(
                              t(
                                "Disconnect and clear this account cache?",
                                "断开连接并清除当前账户缓存？",
                              ),
                            )
                          )
                            void action.run(async () => {
                              await del("/connections/trading212");
                              connections.reload();
                            });
                        }}
                      >
                        {t("Disconnect", "断开")}
                      </button>
                    )}
                    <Button busy={action.busy} secondary>
                      <Save size={15} />
                      {t("Save connection", "保存连接")}
                    </Button>
                  </div>
                </div>
              </form>
            </div>
            <div className="connection-block">
              <div className="connection-title">
                <div className="provider-logo">
                  <KeyRound size={22} />
                </div>
                <div>
                  <h3>{t("OpenAI-compatible API", "OpenAI 兼容 API")}</h3>
                  <p>
                    {t("Cloud or local model endpoint", "云端或本地模型接口")}
                  </p>
                </div>
                <Tag tone={connections.data?.openai.configured ? "green" : ""}>
                  {connections.data?.openai.configured
                    ? t("Configured", "已配置")
                    : t("Not connected", "未连接")}
                </Tag>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void action.run(
                    async () => {
                      await put("/connections/openai", llm);
                      setLlm({ ...llm, api_key: "" });
                      connections.reload();
                    },
                    t("AI connection saved", "AI 连接已保存"),
                  );
                }}
              >
                <div className="form-grid">
                  <label>
                    {t("Base URL", "接口地址")}
                    <input
                      type="url"
                      value={llm.base_url}
                      onChange={(e) =>
                        setLlm({ ...llm, base_url: e.target.value })
                      }
                      required
                    />
                  </label>
                  <label>
                    API Key
                    <input
                      type="password"
                      autoComplete="off"
                      value={llm.api_key}
                      onChange={(e) =>
                        setLlm({ ...llm, api_key: e.target.value })
                      }
                      placeholder={
                        connections.data?.openai.configured
                          ? t(
                              "Saved · leave blank to keep",
                              "已保存 · 留空保留",
                            )
                          : t(
                              "API key (optional for local models)",
                              "API Key（本地模型可留空）",
                            )
                      }
                    />
                  </label>
                </div>
                <p className="field-hint">
                  {t(
                    "Select the model, reasoning effort and editable prompts in Intelligence. Local endpoints need PEAT_LLM_ALLOWED_HOSTS.",
                    "在智能研究中选择模型、思考强度并编辑提示词。本地接口需配置 PEAT_LLM_ALLOWED_HOSTS。",
                  )}
                </p>
                <div className="settings-actions">
                  <span />
                  {connections.data?.openai.configured && (
                    <button
                      type="button"
                      className="text-button danger"
                      onClick={() =>
                        action.run(async () => {
                          await del("/connections/openai");
                          connections.reload();
                        })
                      }
                    >
                      {t("Disconnect", "断开")}
                    </button>
                  )}
                  <Button busy={action.busy} secondary>
                    <Save size={15} />
                    {t("Save connection", "保存连接")}
                  </Button>
                </div>
              </form>
            </div>
            <div className="connection-block">
              <div className="connection-title">
                <div className="provider-logo codex">
                  <Code2 size={22} />
                </div>
                <div>
                  <h3>Codex CLI</h3>
                  <p>
                    {t(
                      "Administrator connection · shared across the workspace",
                      "管理员连接 · 全站共享",
                    )}
                  </p>
                </div>
                <Tag tone={codex.data?.logged_in ? "green" : ""}>
                  {codex.data?.logged_in
                    ? t("Connected", "已连接")
                    : t("Not connected", "未连接")}
                </Tag>
              </div>
              <p className="field-hint">
                {user.role === "admin"
                  ? t(
                      "Sign in once to make Codex available to all workspace users. Open the verification page and enter the device code.",
                      "管理员登录后，全站用户即可使用 Codex。打开验证页面并输入设备码完成登录。",
                    )
                  : codex.data?.logged_in
                    ? t(
                        "Codex is connected by an administrator. Choose Codex and a model in Intelligence.",
                        "管理员已连接 Codex，可在智能研究中选择 Codex 和模型。",
                      )
                    : t(
                        "An administrator needs to connect Codex before it can be used.",
                        "等待管理员连接 Codex 后即可使用。",
                      )}
              </p>
              {loginJob && (
                <div className="device-login" aria-live="polite">
                  {login.data?.user_code ? (
                    <>
                      <span>
                        {t("Your one-time device code", "你的一次性设备码")}
                      </span>
                      <code>{login.data.user_code}</code>
                      <External
                        href={
                          login.data.verification_url ||
                          "https://auth.openai.com/codex/device"
                        }
                      >
                        {t("Open verification page", "打开验证页面")}
                      </External>
                    </>
                  ) : login.data?.status === "failed" ? (
                    <span>
                      {t(
                        "Login failed or expired. Start again.",
                        "登录失败或已过期，请重新开始。",
                      )}
                    </span>
                  ) : (
                    <span>
                      {t("Requesting a device code…", "正在请求设备码…")}
                    </span>
                  )}
                </div>
              )}
              <div className="settings-actions">
                <button className="text-button" onClick={codex.reload}>
                  <RefreshCw size={15} />
                  {t("Check status", "检查状态")}
                </button>
                {user.role === "admin" && (
                  <Button
                    secondary
                    busy={action.busy}
                    disabled={!!loginJob && login.data?.status === "running"}
                    onClick={() =>
                      action.run(async () => {
                        if (codex.data?.logged_in) {
                          await post("/codex/logout");
                          codex.reload();
                        } else {
                          const result = await post("/codex/login");
                          setLoginJob(result.job_id);
                        }
                      })
                    }
                  >
                    {codex.data?.logged_in ? (
                      <>
                        <LogOut size={16} />
                        {t("Disconnect shared Codex", "断开共享 Codex")}
                      </>
                    ) : (
                      <>
                        <ExternalLink size={16} />
                        {t("Start device login", "开始设备登录")}
                      </>
                    )}
                  </Button>
                )}
              </div>
            </div>
          </Panel>
          {user.role === "admin" && <RuntimeSettings />}
        </div>
        <aside className="side-column">
          <Panel title={t("Appearance", "外观")}>
            <div className="preferences">
              <label>{t("Theme", "主题")}</label>
              <div className="theme-options">
                {[
                  ["light", Sun, t("Light", "浅色")],
                  ["dark", Moon, t("Dark", "深色")],
                  ["system", Monitor, t("System", "跟随系统")],
                ].map(([key, Icon, label]) => {
                  const Glyph = Icon as typeof Sun;
                  return (
                    <button
                      key={key as string}
                      className={s.theme === key ? "selected" : ""}
                      onClick={() => {
                        const next = {
                          ...s,
                          theme: key as Preferences["theme"],
                        };
                        setS(next);
                        void action.run(() => saveSettings(next));
                      }}
                    >
                      <Glyph size={20} />
                      <span>{label as string}</span>
                    </button>
                  );
                })}
              </div>
              <label>{t("Accent color", "强调色")}</label>
              <div className="accent-options">
                {["#8a9aff", "#b19aff", "#75c9e4", "#d497c4", "#d5b082"].map(
                  (color) => (
                    <button
                      key={color}
                      className={s.accent === color ? "selected" : ""}
                      style={{ background: color }}
                      aria-label={color}
                      onClick={() => {
                        setS({ ...s, accent: color });
                        void action.run(() =>
                          saveSettings({ ...s, accent: color }),
                        );
                      }}
                    >
                      {s.accent === color && <Check size={15} />}
                    </button>
                  ),
                )}
                <input
                  aria-label={t("Custom accent color", "自定义强调色")}
                  type="color"
                  value={s.accent}
                  onChange={(e) => setS({ ...s, accent: e.target.value })}
                  onBlur={() => action.run(() => saveSettings(s))}
                />
              </div>
              <label>
                {t("Interface language", "界面语言")}
                <select
                  value={s.language}
                  onChange={(e) => {
                    const next = {
                      ...s,
                      language: e.target.value as "en" | "zh",
                    };
                    setS(next);
                    void action.run(() => saveSettings(next));
                  }}
                >
                  <option value="en">English</option>
                  <option value="zh">简体中文</option>
                </select>
              </label>
            </div>
          </Panel>
          <Panel title={t("Data & refresh", "数据与刷新")}>
            <form
              className="preferences"
              onSubmit={(e) => {
                e.preventDefault();
                void action.run(
                  () => saveSettings(s),
                  t("Preferences saved", "偏好已保存"),
                );
              }}
            >
              <label>
                {t("Portfolio refresh (seconds)", "持仓刷新间隔（秒）")}
                <input
                  type="number"
                  min={15}
                  max={3600}
                  value={s.portfolio_interval}
                  onChange={(e) =>
                    setS({ ...s, portfolio_interval: +e.target.value })
                  }
                />
              </label>
              <label>
                {t("News refresh (minutes)", "新闻刷新间隔（分钟）")}
                <input
                  type="number"
                  min={5}
                  max={1440}
                  value={s.news_interval / 60}
                  onChange={(e) =>
                    setS({ ...s, news_interval: +e.target.value * 60 })
                  }
                />
              </label>
              <label>
                {t("Maximum saved articles", "新闻存储条数上限")}
                <input
                  type="number"
                  min={10}
                  max={20000}
                  value={s.news_limit}
                  onChange={(e) => setS({ ...s, news_limit: +e.target.value })}
                />
              </label>
              <label>
                {t("Keep news for (days)", "新闻保留天数")}
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={s.news_days}
                  onChange={(e) => setS({ ...s, news_days: +e.target.value })}
                />
              </label>
              <label>
                {t("News language", "新闻语言")}
                <select
                  value={s.news_language}
                  onChange={(e) =>
                    setS({ ...s, news_language: e.target.value as "en" | "zh" })
                  }
                >
                  <option value="en">English</option>
                  <option value="zh">简体中文</option>
                </select>
              </label>
              <p className="field-hint">
                {t(
                  "Oldest articles are removed automatically when a limit is reached.",
                  "达到上限后自动删除最旧新闻。",
                )}
              </p>
              <Button busy={action.busy}>
                <Check size={15} />
                {t("Save preferences", "保存偏好")}
              </Button>
            </form>
          </Panel>
        </aside>
      </div>
    </>
  );
}

function RuntimeSettings() {
  const { t } = useApp(),
    r = useResource("/admin/runtime"),
    action = useAction();
  const [version, setVersion] = useState(""),
    [job, setJob] = useState<string | null>(null),
    [dependency, setDependency] = useState("codex"),
    [releases, setReleases] = useState<any>(null);
  return (
    <Panel
      title={t("Runtime & dependencies", "运行环境与依赖")}
      sub={t("Administrator controls", "管理员设置")}
    >
      <div className="runtime-info">
        <div>
          <span>Peat</span>
          <strong>v{r.data?.peat || "—"}</strong>
        </div>
        <div>
          <span>Python</span>
          <strong>{r.data?.python || "—"}</strong>
        </div>
        <div>
          <span>Codex CLI</span>
          <strong>{r.data?.codex || "—"}</strong>
        </div>
        <div>
          <span>exchange-calendars</span>
          <strong>{r.data?.calendar || "—"}</strong>
        </div>
      </div>
      <form
        className="runtime-update"
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            const result = await post("/admin/runtime/" + dependency, {
              version,
            });
            setJob(result.job_id);
          });
        }}
      >
        <label>
          {t("Dependency", "依赖")}
          <select
            value={dependency}
            onChange={(e) => {
              setDependency(e.target.value);
              setVersion(releases?.[e.target.value] || "");
            }}
          >
            <option value="codex">Codex CLI</option>
            <option value="calendar">exchange-calendars</option>
          </select>
        </label>
        <label>
          {t("Version to install", "要安装的版本")}
          <input
            placeholder={releases?.[dependency] || "0.155.1"}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            pattern="\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?"
            required
          />
        </label>
        <Button secondary busy={action.busy}>
          <Download size={16} />
          {t("Install", "安装")}
        </Button>
      </form>
      <div className="settings-actions">
        <button
          className="text-button"
          onClick={() =>
            action.run(async () => {
              const result = await api("/admin/runtime/releases");
              setReleases(result);
              setVersion(result[dependency] || "");
            })
          }
        >
          <RefreshCw size={15} />
          {t("Check latest versions", "检查最新版本")}
        </button>
      </div>
      <p className="field-hint">
        {t(
          "Versions are installed in the data volume. Codex updates apply immediately; calendar updates need a service restart.",
          "版本安装到数据卷。Codex 更新立即生效；交易日历更新后需重启服务。",
        )}
      </p>
      <JobOutput id={job} onDone={r.reload} />
    </Panel>
  );
}

export function Admin() {
  const { t } = useApp(),
    r = useResource("/admin/users");
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("WORKSPACE ADMINISTRATION", "工作台管理")}
          </div>
          <h1>{t("People", "用户管理")}</h1>
          <p>
            {t(
              "Manage access, roles and account credentials.",
              "管理用户访问、角色及登录密码。",
            )}
          </p>
        </div>
        <Tag>
          {r.data?.length || 0} {t("users", "位用户")}
        </Tag>
      </div>
      <Panel title={t("Workspace members", "工作台用户")}>
        <div className="admin-list">
          {r.data?.map((u: any) => (
            <UserEditor key={u.id} initial={u} reload={r.reload} />
          ))}
        </div>
        {!!r.error && <ResourceError error={r.error} retry={r.reload} />}
      </Panel>
    </>
  );
}
function UserEditor({ initial, reload }: { initial: any; reload: () => void }) {
  const { t } = useApp(),
    action = useAction();
  const [u, setU] = useState({ ...initial, password: "" });
  return (
    <form
      className="user-editor"
      onSubmit={(e) => {
        e.preventDefault();
        void action.run(
          async () => {
            await put("/admin/users/" + u.id, {
              username: u.username,
              role: u.role,
              active: !!u.active,
              password: u.password,
            });
            setU({ ...u, password: "" });
            reload();
          },
          t("User updated", "用户已更新"),
        );
      }}
    >
      <span className="user-avatar">
        {u.username.slice(0, 2).toUpperCase()}
      </span>
      <label>
        {t("Username", "用户名")}
        <input
          value={u.username}
          onChange={(e) => setU({ ...u, username: e.target.value })}
          minLength={3}
          maxLength={32}
          required
        />
      </label>
      <label>
        {t("Role", "角色")}
        <select
          value={u.role}
          onChange={(e) => setU({ ...u, role: e.target.value })}
        >
          <option value="user">{t("User", "用户")}</option>
          <option value="admin">{t("Administrator", "超级管理员")}</option>
        </select>
      </label>
      <label>
        {t("Reset password", "重置密码")}
        <input
          type="password"
          value={u.password}
          onChange={(e) => setU({ ...u, password: e.target.value })}
          placeholder={t("Leave blank to keep", "留空保留原密码")}
          minLength={10}
          maxLength={128}
          autoComplete="new-password"
        />
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={!!u.active}
          onChange={(e) => setU({ ...u, active: e.target.checked })}
        />
        {t("Active", "启用")}
      </label>
      <Button secondary busy={action.busy}>
        <Save size={16} />
        {t("Save", "保存")}
      </Button>
    </form>
  );
}

export function Console() {
  const { t } = useApp(),
    action = useAction(),
    status = useResource("/admin/runtime");
  const [command, setCommand] = useState(""),
    [jobs, setJobs] = useState<{ id: string; command: string }[]>([]);
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("LOCAL WORKSPACE TOOLS", "本地工作台工具")}
          </div>
          <h1>{t("Console", "本地控制台")}</h1>
          <p>
            {t(
              "Run commands on the Peat server with administrator access.",
              "以管理员身份在 Peat 服务器上执行命令。",
            )}
          </p>
        </div>
        <Tag>{t("Server shell", "服务器命令行")}</Tag>
      </div>
      <div className="console-shell">
        <div className="console-bar">
          <span className="traffic">
            <i />
            <i />
            <i />
          </span>
          <span>peat / workspace</span>
          <span>{t("60s per command", "每条命令限时 60 秒")}</span>
        </div>
        <div className="console-body">
          <div className="console-welcome">
            <span>Peat v{status.data?.peat || "0.1.0"}</span>
            <p>
              {t(
                "Local console ready. Commands use the server service account.",
                "本地控制台已就绪。命令使用服务器服务账户运行。",
              )}
            </p>
          </div>
          {jobs.map((j) => (
            <div key={j.id} className="console-entry">
              <div className="command-echo">
                <span>❯</span> {j.command}
              </div>
              <JobOutput id={j.id} />
            </div>
          ))}
          <form
            className="console-input"
            onSubmit={(e) => {
              e.preventDefault();
              const sent = command;
              void action.run(async () => {
                const r = await post("/admin/console", { command: sent });
                setJobs([...jobs, { id: r.job_id, command: sent }]);
                setCommand("");
              });
            }}
          >
            <span>❯</span>
            <input
              aria-label={t("Shell command", "命令行输入")}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder={t("Enter a command…", "输入命令…")}
              autoComplete="off"
              spellCheck={false}
              required
              maxLength={4000}
            />
            <Button busy={action.busy} disabled={!status.data?.console_enabled}>
              {t("Run", "运行")}
            </Button>
          </form>
        </div>
      </div>
    </>
  );
}
