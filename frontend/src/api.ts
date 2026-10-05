import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";

export type Settings = {
  theme: "light" | "dark" | "system";
  accent: string;
  language: "en" | "zh";
  style: string;
  holding_horizon: "ultra_short" | "short" | "medium_long";
  news_limit: number;
  news_days: number;
  news_interval: number;
  portfolio_interval: number;
  ai_provider: "openai" | "codex";
  ai_model: string;
  reasoning_effort: string;
  news_language: "en" | "zh";
  ai_base_prompt: string;
  ai_style_prompts: Record<string, string>;
  ai_horizon_prompts: Record<string, string>;
};
export type User = {
  id: number;
  username: string;
  role: "admin" | "user";
  active: boolean;
  settings: Settings;
};
export type Translate = (en: string, zh: string) => string;
export const Context = createContext<{
  user: User;
  t: Translate;
  saveSettings: (s: Settings) => Promise<void>;
  notify: (s: string, error?: boolean) => void;
  uiScale: number;
  setUiScale: (scale: number) => void;
}>({} as never);
export const useApp = () => useContext(Context);

export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
  ) {
    super(code);
  }
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = { "X-Peat-Request": "1" };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    ...options,
    headers: { ...headers, ...options.headers },
    credentials: "same-origin",
  });
  const data = await response
    .json()
    .catch(() => ({ detail: "server_unavailable" }));
  if (!response.ok)
    throw new ApiError(
      typeof data.detail === "string" ? data.detail : "invalid_request",
      response.status,
    );
  return data;
}
export const post = <T = any>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
export const put = <T = any>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = (path: string) => api(path, { method: "DELETE" });

const errors: Record<string, [string, string]> = {
  analysis_interrupted: [
    "The server restarted during generation. Start a new brief.",
    "服务重启导致生成中断，请重新生成。",
  ],
  analysis_failed: [
    "Generation failed. Check your provider connection and retry.",
    "生成失败，请检查平台连接后重试。",
  ],
  article_retry_later: [
    "Please wait a few seconds before retrying.",
    "请稍等几秒后重试。",
  ],
  login_required: ["Please sign in again.", "请重新登录。"],
  invalid_credentials: [
    "Incorrect username or password.",
    "用户名或密码错误。",
  ],
  username_taken: ["This username is already in use.", "该用户名已被使用。"],
  too_many_attempts: [
    "Too many attempts. Try again in five minutes.",
    "尝试次数过多，请五分钟后重试。",
  ],
  invalid_request: [
    "Check the entered values. Passwords need at least 10 characters.",
    "请检查输入，密码至少需要 10 位。",
  ],
  broker_not_connected: [
    "Connect Trading 212 in Settings first.",
    "请先在设置中连接 Trading 212。",
  ],
  broker_credentials_rejected: [
    "Trading 212 rejected these credentials or permissions.",
    "Trading 212 凭据或权限验证失败。",
  ],
  broker_keys_required: [
    "Enter both API key and API secret.",
    "请填写 API Key 和 API Secret。",
  ],
  broker_unreachable: [
    "Trading 212 is currently unreachable.",
    "暂时无法连接 Trading 212。",
  ],
  broker_rate_limited: [
    "Trading 212 refresh limit reached. Wait briefly and retry.",
    "已达到 Trading 212 刷新频率限制，请稍后重试。",
  ],
  news_rate_limited: [
    "News was just refreshed. Try again in a minute.",
    "新闻刚刚刷新，请一分钟后重试。",
  ],
  ai_not_connected: [
    "Configure an AI provider in Settings.",
    "请在设置中配置 AI 平台。",
  ],
  models_unavailable: [
    "Model discovery failed. You can enter a model ID manually.",
    "无法读取模型列表，可以手动填写模型 ID。",
  ],
  model_required: [
    "Choose a model before generating a brief.",
    "请先选择模型。",
  ],
  model_or_reasoning_rejected: [
    "The provider rejected this model or reasoning setting. Try Auto or a supported effort.",
    "平台拒绝了模型或思考强度设置，请尝试自动或受支持的强度。",
  ],
  reasoning_not_supported: [
    "This model does not support the selected reasoning effort.",
    "该模型不支持所选思考强度。",
  ],
  model_unavailable: [
    "Refresh the Codex model list and choose an available model.",
    "请刷新 Codex 模型列表并选择可用模型。",
  ],
  analysis_needs_evidence: [
    "Sync your portfolio or collect news first.",
    "请先同步持仓或获取新闻。",
  ],
  analysis_running: ["An analysis is already running.", "已有分析正在生成。"],
  codex_not_installed: [
    "Codex is not installed. An administrator can install it in Settings.",
    "Codex 尚未安装，管理员可在设置中安装。",
  ],
  codex_models_unavailable: [
    "Could not read Codex models. Ask an administrator to check the shared login.",
    "无法读取 Codex 模型，请管理员检查共享登录状态。",
  ],
  codex_analysis_failed: [
    "Codex could not complete the analysis. Check the shared login and model access.",
    "Codex 分析失败，请检查共享登录状态与模型权限。",
  ],
  ai_request_failed: [
    "The AI request failed. Check the endpoint, model and credentials.",
    "AI 请求失败，请检查接口、模型及凭据。",
  ],
  chart_unavailable: [
    "Price history is unavailable for this symbol. Check its Yahoo Finance symbol.",
    "该代码暂无行情，请检查 Yahoo Finance 对应代码。",
  ],
  chart_no_data: [
    "No candles for this time range.",
    "所选时间范围没有 K 线数据。",
  ],
  chart_symbol_required: [
    "Enter the exchange's market symbol, such as AIR.PA, ASML.AS or VUSA.L.",
    "请填写对应交易所的行情代码，例如 AIR.PA、ASML.AS 或 VUSA.L。",
  ],
  invalid_chart_query: [
    "Check the market symbol and selected time range.",
    "请检查行情代码和所选时间范围。",
  ],
  last_admin_required: [
    "Keep at least one active administrator.",
    "至少需要保留一位启用的管理员。",
  ],
  private_api_host_not_allowed: [
    "Add this local host to PEAT_LLM_ALLOWED_HOSTS on the server.",
    "请在服务器 PEAT_LLM_ALLOWED_HOSTS 中添加此本地地址。",
  ],
  https_required: [
    "Use HTTPS, or explicitly allow this local host on the server.",
    "请使用 HTTPS，或在服务器允许此本地地址。",
  ],
  statement_columns_missing: [
    "Import a Trading 212 CSV exported with English column names.",
    "请导入使用英文列名导出的 Trading 212 CSV。",
  ],
  process_timeout: ["The operation timed out.", "操作超时。"],
  server_unavailable: ["The server is unavailable.", "暂时无法连接服务器。"],
  job_already_running: [
    "This operation is already running.",
    "此操作正在运行。",
  ],
  registration_closed: ["Registration is closed.", "注册已关闭。"],
};
export function errorMessage(error: unknown, t: Translate) {
  const key = error instanceof Error ? error.message : "server_unavailable";
  const pair = errors[key];
  return pair ? t(...pair) : t("Operation failed: ", "操作失败：") + key;
}
export function useResource<T = any>(
  path: string | null,
  interval = 0,
  keepPreviousData = true,
) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState<unknown>(null),
    [loading, setLoading] = useState(true);
  const [dataPath, setDataPath] = useState<string | null>(null),
    [errorPath, setErrorPath] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((r) => r + 1), []);
  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let alive = true;
    const controller = new AbortController();
    setLoading(true);
    const run = () =>
      api<T>(path, { signal: controller.signal })
        .then((d) => {
          if (alive) {
            setData(d);
            setDataPath(path);
            setError(null);
          }
        })
        .catch((e) => {
          if (alive && e.name !== "AbortError") {
            setError(e);
            setErrorPath(path);
          }
        })
        .finally(() => {
          if (alive) setLoading(false);
        });
    void run();
    const timer = interval ? window.setInterval(run, interval) : null;
    return () => {
      alive = false;
      controller.abort();
      if (timer) window.clearInterval(timer);
    };
  }, [path, revision, interval]);
  return {
    data: keepPreviousData || dataPath === path ? data : null,
    error: keepPreviousData || errorPath === path ? error : null,
    loading:
      loading ||
      (!keepPreviousData && !!path && dataPath !== path && errorPath !== path),
    reload,
    setData,
  };
}
export function useAction() {
  const { t, notify } = useApp();
  const [busy, setBusy] = useState(false);
  return {
    busy,
    run: async (fn: () => Promise<unknown>, success?: string) => {
      setBusy(true);
      try {
        const r = await fn();
        if (success) notify(success);
        return r;
      } catch (e) {
        notify(errorMessage(e, t), true);
      } finally {
        setBusy(false);
      }
    },
  };
}
export const money = (
  n: number | null | undefined,
  currency = "EUR",
  lang = "en",
) =>
  n == null
    ? "—"
    : new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-GB", {
        style: "currency",
        currency: currency || "EUR",
        maximumFractionDigits: 2,
      }).format(n);
export const num = (n: number | null | undefined, digits = 2) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(
        n,
      );
export const date = (s: string | undefined, lang = "en") =>
  s
    ? new Date(s).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";
export const styles = [
  ["very_conservative", "Very conservative", "极度保守"],
  ["conservative", "Conservative", "保守"],
  ["balanced", "Balanced", "常规"],
  ["aggressive", "Aggressive", "激进"],
  ["very_aggressive", "Very aggressive", "极度激进"],
];
export const holdingHorizons = [
  [
    "ultra_short",
    "Ultra short term",
    "超短线",
    "Intraday–3 trading days",
    "当日–3 个交易日",
  ],
  ["short", "Short term", "短线", "1–4 weeks", "1–4 周"],
  [
    "medium_long",
    "Medium / long term",
    "中长线",
    "1 month or longer",
    "1 个月以上",
  ],
] as const;
export function horizonLabel(value: string | null | undefined, t: Translate) {
  const item = holdingHorizons.find((h) => h[0] === value);
  return item ? t(item[1], item[2]) : "";
}
