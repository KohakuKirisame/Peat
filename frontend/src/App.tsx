import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Bell,
  ChartCandlestick,
  Check,
  ChevronRight,
  Globe2,
  LayoutDashboard,
  Leaf,
  LoaderCircle,
  LogOut,
  Menu,
  Moon,
  Newspaper,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  Sprout,
  Star,
  Sun,
  Terminal,
  Users,
  Wallet,
  X,
  History as HistoryIcon,
} from "lucide-react";
import { api, Context, errorMessage, post } from "./api";
import type { Settings as Preferences, User } from "./api";
import { Button } from "./ui";
import { MarketsPanel, Overview, Watchlist } from "./Overview";
import Intelligence from "./Intelligence";
import { History, News } from "./NewsHistory";
import Settings, { Admin, Console } from "./Settings";
import { AnalysisTasks, AnalysisTaskBanner } from "./AnalysisTasks";
import { useUiScale } from "./useUiScale";

export default function App() {
  const settingsQueue = useRef<Promise<unknown>>(Promise.resolve());
  const settingsRevision = useRef(0);
  const [user, setUser] = useState<User | null>(null),
    [ready, setReady] = useState(false),
    [page, setPage] = useState(location.hash.slice(1) || "overview"),
    [mobile, setMobile] = useState(false),
    [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [guestLang, setGuestLang] = useState<"en" | "zh">(
    localStorage.getItem("peat_language") === "zh" ? "zh" : "en",
  );
  const lang = user?.settings.language || guestLang,
    t = (en: string, zh: string) => (lang === "zh" ? zh : en);
  const { scale: uiScale, setScale: setUiScale } = useUiScale(user?.id);
  useEffect(() => {
    api<User>("/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);
  useEffect(() => {
    const onHash = () => setPage(location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const settings = user?.settings,
      query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        settings?.theme === "system"
          ? query.matches
            ? "dark"
            : "light"
          : settings?.theme || "dark";
      document.documentElement.style.setProperty(
        "--accent",
        settings?.accent || "#8a9aff",
      );
      const accent = settings?.accent || "#8a9aff";
      const rgb = [1, 3, 5]
        .map((i) => parseInt(accent.slice(i, i + 2), 16) / 255)
        .map((v) =>
          v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4),
        );
      const luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
      document.documentElement.style.setProperty(
        "--on-accent",
        luminance > 0.22 ? "#10162e" : "#ffffff",
      );
      document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    };
    apply();
    query.addEventListener("change", apply);
    localStorage.setItem("peat_language", lang);
    return () => query.removeEventListener("change", apply);
  }, [user?.settings, lang]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  const notify = (text: string, error = false) => setToast({ text, error });
  const navigate = (key: string) => {
    location.hash = key;
    setPage(key);
    setMobile(false);
    window.scrollTo(0, 0);
  };
  const saveSettings = async (settings: Preferences) => {
    const revision = ++settingsRevision.current;
    const pending = settingsQueue.current
      .catch(() => {})
      .then(() =>
        api("/settings", { method: "PUT", body: JSON.stringify(settings) }),
      );
    settingsQueue.current = pending;
    await pending;
    if (revision === settingsRevision.current) {
      setUser((u) => (u ? { ...u, settings } : u));
    }
  };
  const nav = [
    ["overview", LayoutDashboard, t("Overview", "总览")],
    ["portfolio", Wallet, t("Portfolio", "投资组合")],
    ["watchlist", Star, t("Watchlist", "关注列表")],
    ["markets", Globe2, t("Markets", "市场")],
    ["news", Newspaper, t("Newsroom", "新闻室")],
    ["intelligence", Sparkles, t("Intelligence", "智能研究")],
    ["history", HistoryIcon, t("Activity", "账户流水")],
  ] as const;
  if (!ready)
    return (
      <div className="app-loading">
        <img src="/peat-logo.png" alt="Peat" />
        <LoaderCircle className="spin" size={24} />
      </div>
    );
  if (!user)
    return <Auth onLogin={setUser} lang={guestLang} setLang={setGuestLang} />;
  return (
    <Context.Provider
      value={{ user, t, saveSettings, notify, uiScale, setUiScale }}
    >
      <AnalysisTasks key={user.id}>
        <a href="#main-content" className="skip-link">
          {t("Skip to content", "跳至正文")}
        </a>
        <div className="app-shell">
          {mobile && (
            <button
              className="sidebar-overlay"
              aria-label={t("Close navigation", "关闭导航")}
              onClick={() => setMobile(false)}
            />
          )}
          <aside className={`sidebar ${mobile ? "is-open" : ""}`}>
            <button className="brand" onClick={() => navigate("overview")}>
              <img src="/peat-logo.png" alt="" />
              <span>
                Peat<span className="brand-dot">.</span>
              </span>
            </button>
            <div className="workspace-switch">
              <div className="workspace-icon">
                <Leaf size={18} />
              </div>
              <div>
                <strong>{t("Personal workspace", "个人工作台")}</strong>
                <small>{t("Investment intelligence", "投资研究助手")}</small>
              </div>
              <ChevronRight size={14} />
            </div>
            <div className="nav-label">{t("WORKSPACE", "工作台")}</div>
            <nav aria-label={t("Main navigation", "主导航")}>
              {nav.map(([key, Icon, label]) => (
                <button
                  key={key}
                  onClick={() => navigate(key)}
                  className={page === key ? "active" : ""}
                  aria-current={page === key ? "page" : undefined}
                >
                  <Icon size={18} />
                  <span>{label}</span>
                  {key === "intelligence" && <span className="nav-ai">AI</span>}
                </button>
              ))}
            </nav>
            <div className="sidebar-bottom">
              <div className="nav-label">{t("MANAGE", "管理")}</div>
              <nav>
                <button
                  onClick={() => navigate("settings")}
                  className={page === "settings" ? "active" : ""}
                >
                  <SettingsIcon size={18} />
                  <span>{t("Settings", "设置")}</span>
                </button>
                {user.role === "admin" && (
                  <>
                    <button
                      onClick={() => navigate("console")}
                      className={page === "console" ? "active" : ""}
                    >
                      <Terminal size={18} />
                      <span>{t("Console", "本地控制台")}</span>
                    </button>
                    <button
                      onClick={() => navigate("admin")}
                      className={page === "admin" ? "active" : ""}
                    >
                      <Users size={18} />
                      <span>{t("People", "用户管理")}</span>
                    </button>
                  </>
                )}
              </nav>
              <div className="sidebar-note">
                <Sprout size={19} />
                <p>
                  {t(
                    "Stay curious.\nInvest thoughtfully.",
                    "保持好奇，\n审慎思考。",
                  )}
                </p>
              </div>
              <div className="user-menu">
                <span className="user-avatar">
                  {user.username.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <strong>{user.username}</strong>
                  <small>
                    {user.role === "admin"
                      ? t("Administrator", "超级管理员")
                      : t("Member", "用户")}
                  </small>
                </div>
                <button
                  className="icon-button"
                  aria-label={t("Sign out", "退出登录")}
                  onClick={async () => {
                    try {
                      await post("/auth/logout");
                      setUser(null);
                    } catch (e) {
                      notify(errorMessage(e, t), true);
                    }
                  }}
                >
                  <LogOut size={16} />
                </button>
              </div>
            </div>
          </aside>
          <div className="workspace-main">
            <header className="topbar">
              <div className="breadcrumb">
                <button
                  className="icon-button mobile-menu"
                  aria-label={t("Open navigation", "打开导航")}
                  onClick={() => setMobile(true)}
                >
                  <Menu size={21} />
                </button>
                <span>Workspace</span>
                <ChevronRight size={13} />
                <strong>
                  {nav.find((n) => n[0] === page)?.[2] ||
                    (
                      {
                        settings: t("Settings", "设置"),
                        console: t("Console", "控制台"),
                        admin: t("People", "用户管理"),
                      } as Record<string, string>
                    )[page] ||
                    t("Overview", "总览")}
                </strong>
              </div>
              <div className="topbar-actions">
                <select
                  className="zoom-select"
                  aria-label={t("Interface zoom", "界面缩放")}
                  title={t("Interface zoom", "界面缩放")}
                  value={uiScale}
                  onChange={(e) => setUiScale(Number(e.target.value))}
                >
                  {Array.from(
                    new Set([80, 90, 100, 110, 125, 150, 175, 200, uiScale]),
                  )
                    .sort((a, b) => a - b)
                    .map((value) => (
                      <option key={value} value={value}>
                        {value}%
                      </option>
                    ))}
                </select>
                <span className="today">
                  {new Date().toLocaleDateString(
                    lang === "zh" ? "zh-CN" : "en-GB",
                    { day: "numeric", month: "short", year: "numeric" },
                  )}
                </span>
                <button
                  className="icon-button language-toggle"
                  onClick={() =>
                    saveSettings({
                      ...user.settings,
                      language: lang === "en" ? "zh" : "en",
                    }).catch((e) => notify(errorMessage(e, t), true))
                  }
                  aria-label={t("Switch to Chinese", "Switch to English")}
                >
                  {lang === "en" ? "中" : "EN"}
                </button>
                <button
                  className="icon-button"
                  aria-label={t("Toggle theme", "切换主题")}
                  onClick={() =>
                    saveSettings({
                      ...user.settings,
                      theme:
                        document.documentElement.dataset.theme === "dark"
                          ? "light"
                          : "dark",
                    }).catch((e) => notify(errorMessage(e, t), true))
                  }
                >
                  {document.documentElement.dataset.theme === "dark" ? (
                    <Sun size={18} />
                  ) : (
                    <Moon size={18} />
                  )}
                </button>
                <span className="header-avatar">
                  {user.username[0].toUpperCase()}
                </span>
              </div>
            </header>
            <AnalysisTaskBanner navigate={navigate} />
            <main id="main-content" className="content" key={page}>
              {page === "overview" ? (
                <Overview navigate={navigate} />
              ) : page === "portfolio" ? (
                <Overview navigate={navigate} portfolioOnly />
              ) : page === "watchlist" ? (
                <Watchlist />
              ) : page === "markets" ? (
                <>
                  <div className="page-title">
                    <div>
                      <div className="eyebrow">
                        {t("A WIDER PERSPECTIVE", "拓展市场视野")}
                      </div>
                      <h1>{t("Global markets", "全球市场")}</h1>
                      <p>
                        {t(
                          "Rates, resources and exchange sessions, in one view.",
                          "集中查看利率、商品价格和交易时段。",
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="markets-page">
                    <MarketsPanel full />
                  </div>
                </>
              ) : page === "news" ? (
                <News />
              ) : page === "intelligence" ? (
                <Intelligence />
              ) : page === "history" ? (
                <History />
              ) : page === "settings" ? (
                <Settings />
              ) : page === "console" && user.role === "admin" ? (
                <Console />
              ) : page === "admin" && user.role === "admin" ? (
                <Admin />
              ) : (
                <Overview navigate={navigate} />
              )}
              <footer className="footer">
                <span>
                  Peat <b>·</b>{" "}
                  {t("Independent by design.", "独立研究，清晰判断。")}
                </span>
                <a
                  href="https://github.com/KohakuKirisame/Peat"
                  target="_blank"
                  rel="noreferrer"
                >
                  AGPL-3.0 <span>↗</span>
                </a>
              </footer>
            </main>
          </div>
        </div>
        {toast && (
          <div
            className={`toast ${toast.error ? "error" : ""}`}
            role={toast.error ? "alert" : "status"}
          >
            {toast.error ? <CircleAlertIcon /> : <Check size={18} />}
            <span>{toast.text}</span>
            <button
              aria-label={t("Dismiss", "关闭")}
              onClick={() => setToast(null)}
            >
              <X size={15} />
            </button>
          </div>
        )}
      </AnalysisTasks>
    </Context.Provider>
  );
}

function CircleAlertIcon() {
  return <span className="error-symbol">!</span>;
}
function Auth({
  onLogin,
  lang,
  setLang,
}: {
  onLogin: (u: User) => void;
  lang: "en" | "zh";
  setLang: (l: "en" | "zh") => void;
}) {
  const t = (en: string, zh: string) => (lang === "zh" ? zh : en);
  const [setup, setSetup] = useState<any>(null),
    [register, setRegister] = useState(false),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/auth/setup")
      .then((s) => {
        setSetup(s);
        setRegister(s.setup_required);
      })
      .catch((e) => setError(errorMessage(e, t)));
  }, []);
  return (
    <div className="auth-page">
      <div className="auth-art">
        <div className="auth-brand">
          <img src="/peat-logo.png" alt="Peat logo" />
          <span>Peat.</span>
        </div>
        <div className="auth-message">
          <div className="eyebrow">
            {t("PERSONAL INVESTMENT INTELLIGENCE", "个人投资研究助手")}
          </div>
          <h1>{t("See the bigger\npicture.", "看见市场，\n看清投资。")}</h1>
          <p>
            {t(
              "Your portfolio. The market around it.\nA perspective that is yours.",
              "你的持仓，周围的市场，\n以及属于你的判断。",
            )}
          </p>
        </div>
        <div className="peat-topography">
          <div />
          <div />
          <div />
          <div />
          <div />
        </div>
        <div className="auth-art-footer">
          <Sprout size={19} />
          <span>{t("Rooted in research.", "让研究成为判断的依据。")}</span>
          <span>EST. 2026</span>
        </div>
      </div>
      <div className="auth-form-side">
        <button
          className="auth-language"
          onClick={() => setLang(lang === "en" ? "zh" : "en")}
        >
          <Globe2 size={16} />
          {lang === "en" ? "简体中文" : "English"}
        </button>
        <form
          className="auth-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              onLogin(
                await post("/auth/" + (register ? "register" : "login"), {
                  username,
                  password,
                }),
              );
            } catch (e) {
              setError(errorMessage(e, t));
            } finally {
              setBusy(false);
            }
          }}
        >
          <span className="welcome-icon">
            <Leaf size={27} />
          </span>
          <h2>
            {setup?.setup_required
              ? t("Make yourself at home.", "创建你的研究工作台。")
              : register
                ? t("A fresh perspective starts here.", "从这里开启新的视角。")
                : t("Welcome back.", "欢迎回来。")}
          </h2>
          <p>
            {setup?.setup_required
              ? t(
                  "Create the first account to become the workspace administrator.",
                  "创建首个账户，成为工作台超级管理员。",
                )
              : register
                ? t(
                    "Create your personal Peat account.",
                    "创建你的 Peat 个人账户。",
                  )
                : t(
                    "Sign in to your investment workspace.",
                    "登录你的投资研究工作台。",
                  )}
          </p>
          <label htmlFor="username">
            {t("Username", "用户名")}
            <input
              id="username"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              maxLength={32}
              pattern="[A-Za-z0-9_.\-]+"
              placeholder={t("Your username", "你的用户名")}
              required
            />
          </label>
          <label htmlFor="password">
            {t("Password", "密码")}
            <input
              id="password"
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={10}
              maxLength={128}
              placeholder={t("At least 10 characters", "至少 10 位字符")}
              required
            />
          </label>
          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}
          <Button busy={busy} className="auth-submit">
            {register ? t("Create account", "创建账户") : t("Sign in", "登录")}
            <ArrowRight size={17} />
          </Button>
          {!setup?.setup_required && setup?.registration_open && (
            <div className="auth-switch">
              {register
                ? t("Already have an account?", "已有账户？")
                : t("New to Peat?", "第一次使用 Peat？")}
              <button
                type="button"
                onClick={() => {
                  setRegister(!register);
                  setError("");
                }}
              >
                {register
                  ? t("Sign in", "登录")
                  : t("Create an account", "注册账户")}
              </button>
            </div>
          )}
          <div className="auth-local">
            <ShieldCheck size={16} />
            {t(
              "Self-hosted. Local accounts, encrypted credentials.",
              "自主部署，账户数据保存在你的工作台。",
            )}
          </div>
        </form>
        <div className="auth-footer">Peat · Investment intelligence</div>
      </div>
    </div>
  );
}
