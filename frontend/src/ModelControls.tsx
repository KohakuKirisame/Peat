import { useEffect, useId, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, errorMessage, useApp } from "./api";
import type { Settings } from "./api";

export function ModelControls({
  settings,
  onChange,
}: {
  settings: Settings;
  onChange: (s: Settings) => void;
}) {
  const { t, notify } = useApp();
  const listId = useId();
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
            list={listId}
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
        <datalist id={listId}>
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
