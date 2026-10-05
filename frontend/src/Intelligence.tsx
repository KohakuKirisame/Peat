import { useEffect, useState } from "react";
import { Markdown } from "./Markdown";
import { useAnalysisTask } from "./AnalysisTasks";
import {
  ArrowUpRight,
  BookOpenText,
  Check,
  ChevronDown,
  Cpu,
  FileText,
  RefreshCw,
  RotateCcw,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Sprout,
} from "lucide-react";
import type { Settings } from "./api";
import {
  api,
  date,
  errorMessage,
  post,
  styles,
  useAction,
  useApp,
  useResource,
} from "./api";
import {
  Button,
  Empty,
  External,
  Loading,
  Panel,
  ResourceError,
  Tag,
} from "./ui";

export function ModelControls({
  settings,
  onChange,
}: {
  settings: Settings;
  onChange: (s: Settings) => void;
}) {
  const { t, notify } = useApp();
  const [models, setModels] = useState<any[]>([]),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    setModels([]);
  }, [settings.ai_provider]);
  async function discover() {
    setLoading(true);
    try {
      setModels(await api("/ai/models?provider=" + settings.ai_provider));
    } catch (e) {
      notify(errorMessage(e, t), true);
    } finally {
      setLoading(false);
    }
  }
  const selected = models.find((m) => m.id === settings.ai_model);
  const efforts = selected?.efforts ?? [
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
  ];
  const labels: Record<string, string> = {
    auto: t("Auto · provider default", "自动 · 平台默认"),
    none: t("None", "无"),
    minimal: t("Minimal", "最小"),
    low: t("Low", "低"),
    medium: t("Medium", "中"),
    high: t("High", "高"),
    xhigh: t("Extra high", "极高"),
    max: t("Max", "最大"),
    ultra: t("Ultra", "超高"),
  };
  return (
    <div className="model-controls">
      <label>
        {t("Provider", "平台")}
        <select
          aria-label={t("Provider", "平台")}
          value={settings.ai_provider}
          onChange={(e) =>
            onChange({
              ...settings,
              ai_provider: e.target.value as "openai" | "codex",
              ai_model: "",
              reasoning_effort: "auto",
            })
          }
        >
          <option value="openai">
            {t("OpenAI-compatible", "OpenAI 兼容接口")}
          </option>
          <option value="codex">Codex CLI</option>
        </select>
      </label>
      <label className="model-field">
        {t("Model", "模型")}
        <div className="input-action">
          <input
            list="model-options"
            value={settings.ai_model}
            placeholder={t("Choose or enter a model ID", "选择或输入模型 ID")}
            onChange={(e) =>
              onChange({
                ...settings,
                ai_model: e.target.value,
                reasoning_effort: "auto",
              })
            }
            maxLength={120}
          />
          <button
            onClick={discover}
            disabled={loading}
            aria-label={t("Load model list", "读取模型列表")}
          >
            <RefreshCw size={16} className={loading ? "spin" : ""} />
          </button>
        </div>
        <datalist id="model-options">
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </datalist>
      </label>
      <label>
        {t("Reasoning effort", "思考强度")}
        <select
          aria-label={t("Reasoning effort", "思考强度")}
          value={settings.reasoning_effort}
          onChange={(e) =>
            onChange({ ...settings, reasoning_effort: e.target.value })
          }
        >
          {["auto", ...efforts].map((e) => (
            <option key={e} value={e}>
              {labels[e] || e}
            </option>
          ))}
        </select>
      </label>
      <p className="field-hint full-width">
        {settings.ai_provider === "codex"
          ? t(
              "Refresh models after the administrator connects Codex. Effort options come from the shared account.",
              "管理员连接 Codex 后刷新模型，可用思考强度来自共享账户。",
            )
          : t(
              "Model IDs come from /models. Compatible providers may support different effort levels; Auto omits the parameter.",
              "模型列表读取自 /models。兼容平台对思考强度的支持不同；自动模式不发送该参数。",
            )}
      </p>
    </div>
  );
}

export default function Intelligence() {
  const analysisTask = useAnalysisTask();
  const { t, user, saveSettings, notify } = useApp(),
    r = useResource<any[]>("/ai/analyses"),
    defaults = useResource("/ai/prompts");
  const [settings, setSettings] = useState(user.settings),
    [promptOpen, setPromptOpen] = useState(false),
    [promptStyle, setPromptStyle] = useState(user.settings.style),
    [current, setCurrent] = useState<number | null>(null),
    [evidenceOpen, setEvidenceOpen] = useState(false);
  const action = useAction(),
    save = useAction();
  useEffect(() => setSettings(user.settings), [user.settings]);
  const analysis = r.data?.find((a) => a.id === current) || r.data?.[0];
  useEffect(() => {
    if (
      analysisTask.job?.status === "completed" &&
      analysisTask.job.analysis_id
    ) {
      setCurrent(analysisTask.job.analysis_id);
      r.reload();
    }
  }, [analysisTask.job?.id, analysisTask.job?.status]);
  const selectedStyle = styles.find((s) => s[0] === settings.style);
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("RESEARCH, WITH PERSPECTIVE", "为判断提供依据")}
          </div>
          <h1>{t("Peat intelligence", "Peat 智能研究")}</h1>
          <p>
            {t(
              "Connect the dots between your holdings, the market and the news.",
              "综合持仓、宏观市场与新闻，形成有依据的判断。",
            )}
          </p>
        </div>
        <Tag tone="green">
          <Sprout size={14} />
          {t("Your research desk", "你的研究工作台")}
        </Tag>
      </div>
      <div className="intelligence-layout">
        <div className="main-column">
          <Panel
            title={t("Shape your perspective", "设定研究偏好")}
            sub={t(
              "Investment style and model reasoning are independent settings.",
              "投资风格与模型思考强度分别设置。",
            )}
          >
            <div
              className="style-selector"
              role="group"
              aria-label={t("Investment style", "投资风格")}
            >
              {styles.map((s, i) => (
                <button
                  key={s[0]}
                  onClick={() => setSettings({ ...settings, style: s[0] })}
                  aria-pressed={settings.style === s[0]}
                  className={settings.style === s[0] ? "selected" : ""}
                >
                  <span className="style-bars">
                    {[0, 1, 2, 3, 4].map((n) => (
                      <i
                        key={n}
                        style={{
                          height: 6 + n * 3,
                          opacity: n <= i ? 1 : 0.18,
                        }}
                      />
                    ))}
                  </span>
                  <span>{t(s[1], s[2])}</span>
                </button>
              ))}
            </div>
            <ModelControls settings={settings} onChange={setSettings} />
            <div className="settings-actions">
              <button
                className="text-button"
                onClick={() => setPromptOpen(!promptOpen)}
              >
                <SlidersHorizontal size={16} />
                {t("Edit research prompts", "编辑研究提示词")}
                <ChevronDown size={15} />
              </button>
              <Button
                secondary
                busy={save.busy}
                onClick={() =>
                  save.run(
                    () => saveSettings(settings),
                    t("Research preferences saved", "研究偏好已保存"),
                  )
                }
              >
                <Check size={16} />
                {t("Save preferences", "保存偏好")}
              </Button>
            </div>
          </Panel>
          {promptOpen && (
            <Panel
              title={t("Prompt studio", "提示词编辑器")}
              sub={t(
                "A shared foundation, with a separate template for each investment style.",
                "通用提示词与五档策略模板，可分别调整。",
              )}
            >
              <div className="prompt-editor">
                <label>
                  {t("Base research prompt", "通用研究提示词")}
                  <textarea
                    aria-label={t("Base research prompt", "通用研究提示词")}
                    rows={13}
                    maxLength={15000}
                    value={settings.ai_base_prompt || defaults.data?.base || ""}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        ai_base_prompt: e.target.value,
                      })
                    }
                  />
                </label>
                <button
                  className="text-button"
                  onClick={() =>
                    setSettings({ ...settings, ai_base_prompt: "" })
                  }
                >
                  <RotateCcw size={14} />
                  {t("Restore base prompt", "恢复通用默认提示词")}
                </button>
                <label>
                  {t("Strategy template", "策略模板")}
                  <select
                    value={promptStyle}
                    onChange={(e) => setPromptStyle(e.target.value)}
                  >
                    {styles.map((s) => (
                      <option key={s[0]} value={s[0]}>
                        {t(s[1], s[2])}
                      </option>
                    ))}
                  </select>
                  <textarea
                    rows={7}
                    maxLength={8000}
                    value={
                      settings.ai_style_prompts[promptStyle] ||
                      defaults.data?.styles?.[promptStyle] ||
                      ""
                    }
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        ai_style_prompts: {
                          ...settings.ai_style_prompts,
                          [promptStyle]: e.target.value,
                        },
                      })
                    }
                  />
                </label>
                <div className="settings-actions">
                  <button
                    className="text-button"
                    onClick={() => {
                      const next = { ...settings.ai_style_prompts };
                      delete next[promptStyle];
                      setSettings({ ...settings, ai_style_prompts: next });
                    }}
                  >
                    <RotateCcw size={14} />
                    {t("Restore this strategy", "恢复此策略默认提示词")}
                  </button>
                  <Button
                    busy={save.busy}
                    onClick={() =>
                      save.run(
                        () => saveSettings(settings),
                        t("Prompts saved", "提示词已保存"),
                      )
                    }
                  >
                    {t("Save prompts", "保存提示词")}
                  </Button>
                </div>
              </div>
            </Panel>
          )}
          <Panel
            title={t("Your research brief", "你的研究简报")}
            sub={t(
              "A synthesis of your portfolio, macro signals and saved news.",
              "基于当前持仓、宏观数据及本地新闻综合生成。",
            )}
            action={
              <Button
                busy={action.busy || analysisTask.starting}
                disabled={analysisTask.active}
                onClick={() =>
                  action.run(async () => {
                    await saveSettings(settings);
                    await analysisTask.start();
                  })
                }
              >
                <Sparkles size={16} />
                {analysisTask.active
                  ? t("Running in background", "后台生成中")
                  : t("Generate brief", "生成简报")}
              </Button>
            }
          >
            {analysisTask.active && (
              <div className="research-progress">
                <div className="pulsing-orb">
                  <Sprout size={28} />
                </div>
                <strong>
                  {t("Building your perspective", "正在形成研究判断")}
                </strong>
                <p>
                  {t(
                    "You can use other pages or close this page. The task has no generation time limit; stop it from the status bar whenever needed.",
                    "可以切换页面或关闭当前页面，任务会在后台继续。生成不设时限，可随时从状态栏手动中止。",
                  )}
                </p>
              </div>
            )}
            {analysis ? (
              <>
                <div className="brief-meta">
                  <Tag tone="green">
                    {
                      styles.find((s) => s[0] === analysis.style)?.[
                        user.settings.language === "zh" ? 2 : 1
                      ]
                    }
                  </Tag>
                  <span>
                    {analysis.model} · {analysis.reasoning_effort}
                  </span>
                  <span>
                    {date(analysis.created_at, user.settings.language)}
                  </span>
                </div>
                <div className="brief-content">
                  <Markdown content={analysis.content} />
                </div>
                <button
                  className="text-button evidence-toggle"
                  onClick={() => setEvidenceOpen(!evidenceOpen)}
                >
                  <BookOpenText size={16} />
                  {t("View evidence & saved prompt", "查看依据与当时提示词")}
                  <ChevronDown size={16} />
                </button>
                {evidenceOpen && (
                  <div className="evidence">
                    <p>
                      {t("Portfolio snapshot", "持仓快照")} ·{" "}
                      {date(
                        analysis.evidence?.portfolio?.updated_at,
                        user.settings.language,
                      )}
                    </p>
                    <p>
                      {t("Market snapshot", "行情快照")} ·{" "}
                      {date(
                        analysis.evidence?.markets?.updated_at,
                        user.settings.language,
                      )}
                    </p>
                    {analysis.evidence?.news_selection && (
                      <p>
                        {t("Relevant stories selected", "按持仓与行业筛选新闻")}{" "}
                        · {analysis.evidence.news_selection.selected_count}
                        {" / "}
                        {analysis.evidence.news_selection.candidate_count}
                      </p>
                    )}
                    {analysis.evidence?.news?.map((n: any) => (
                      <p key={n.id}>
                        <span>[news {n.id}] </span>
                        <External href={n.url}>{n.title}</External>
                        {n.related_entities?.length > 0 && (
                          <small className="evidence-related">
                            {t("Related to", "关联")} ·{" "}
                            {Array.from(
                              new Set(
                                n.related_entities.map(
                                  (entity: any) => entity.name,
                                ),
                              ),
                            ).join(" · ")}
                            {" · "}
                            {n.content_kind === "rss_excerpt"
                              ? t("RSS excerpt", "RSS 摘要")
                              : t("Article text", "新闻正文")}
                          </small>
                        )}
                      </p>
                    ))}
                    <details>
                      <summary>
                        {t(
                          "Prompt used for this brief",
                          "本次简报使用的提示词",
                        )}
                      </summary>
                      <pre>
                        {analysis.evidence?.prompts?.base}
                        {"\n\n"}
                        {analysis.evidence?.prompts?.style}
                      </pre>
                    </details>
                  </div>
                )}
              </>
            ) : (
              <Empty
                icon={<Sparkles size={25} />}
                title={t(
                  "Your next insight starts here",
                  "从这里开始你的下一份洞察",
                )}
                body={t(
                  "Choose your style and model, then generate a brief from your connected data.",
                  "选择投资风格和模型，使用已连接的数据生成研究简报。",
                )}
              />
            )}
            {!!r.error && <ResourceError error={r.error} retry={r.reload} />}
          </Panel>
        </div>
        <aside className="side-column">
          <div className="research-context">
            <Sprout size={26} />
            <h3>{t("Grounded in your world.", "研究围绕你的持仓展开。")}</h3>
            <p>
              {t(
                "Every brief brings together three layers of evidence.",
                "每份简报综合三类证据。",
              )}
            </p>
            {[
              [
                t("Your portfolio", "你的持仓"),
                t("Exposure, concentration & P&L", "敞口、集中度与盈亏"),
              ],
              [
                t("The macro picture", "宏观环境"),
                t(
                  "Treasury yields, energy & metals",
                  "美债收益率、能源与贵金属",
                ),
              ],
              [
                t("Relevant developments", "相关动态"),
                t("Company & industry news", "公司与行业新闻"),
              ],
            ].map(([a, b], i) => (
              <div className="context-item" key={a}>
                <span>0{i + 1}</span>
                <div>
                  <strong>{a}</strong>
                  <small>{b}</small>
                </div>
              </div>
            ))}
          </div>
          <Panel title={t("Research archive", "研究档案")}>
            <div className="archive-list">
              {r.data?.length ? (
                r.data.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      setCurrent(a.id);
                      setEvidenceOpen(false);
                    }}
                    className={analysis?.id === a.id ? "selected" : ""}
                  >
                    <FileText size={17} />
                    <div>
                      <strong>
                        {
                          styles.find((s) => s[0] === a.style)?.[
                            user.settings.language === "zh" ? 2 : 1
                          ]
                        }
                      </strong>
                      <small>
                        {date(a.created_at, user.settings.language)}
                      </small>
                      <small>{a.model}</small>
                    </div>
                    <ArrowUpRight size={14} />
                  </button>
                ))
              ) : (
                <p className="muted padded">
                  {t(
                    "Saved briefs will appear here.",
                    "生成后的简报会保存在这里。",
                  )}
                </p>
              )}
            </div>
          </Panel>
        </aside>
      </div>
    </>
  );
}
