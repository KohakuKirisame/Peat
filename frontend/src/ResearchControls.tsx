import type { Settings } from "./api";
import { useApp } from "./api";

export function ResearchControls({
  settings,
  onChange,
  followup = false,
}: {
  settings: Settings;
  onChange: (value: Settings) => void;
  followup?: boolean;
}) {
  const { t } = useApp();
  const live = settings.ai_live_data !== false;
  return (
    <div className="research-controls">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={live}
          onChange={(e) =>
            onChange({ ...settings, ai_live_data: e.target.checked })
          }
        />
        {followup
          ? t("Refresh data for this reply", "追问前刷新行情与新闻")
          : t("Refresh portfolio, prices and news", "刷新持仓、行情与新闻")}
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.ai_market_tools !== false}
          disabled={!live}
          onChange={(e) =>
            onChange({ ...settings, ai_market_tools: e.target.checked })
          }
        />
        {t(
          "Let the model check quotes, history and news as needed",
          "允许模型按需查价、查询走势和核对新闻",
        )}
      </label>
      {settings.ai_provider === "codex" && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={settings.ai_web_search !== false}
            disabled={!live}
            onChange={(e) =>
              onChange({ ...settings, ai_web_search: e.target.checked })
            }
          />
          {t("Codex live web research", "Codex 联网检索")}
        </label>
      )}
      {!live && (
        <p className="field-hint">
          {followup
            ? t(
                "Review the original report at its saved dates.",
                "按原报告当时保存的数据复盘。",
              )
            : t(
                "Use existing saved evidence for this brief.",
                "使用已有资料生成本次简报。",
              )}
        </p>
      )}
    </div>
  );
}
