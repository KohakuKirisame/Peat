import { useEffect, useState } from "react";
import { api, useAction, useApp, useResource } from "./api";
import { Button, Panel, ResourceError } from "./ui";

export function ReportStorage() {
  const { t, user, saveSettings, notify } = useApp();
  const [limit, setLimit] = useState(user.settings.analysis_limit ?? 0);
  const storage = useResource<{ count: number; limit: number }>("/ai/storage");
  const action = useAction();
  useEffect(
    () => setLimit(user.settings.analysis_limit ?? 0),
    [user.settings.analysis_limit],
  );
  return (
    <Panel
      title={t("Research storage", "分析报告存储")}
      sub={t(
        "Keep the most recently used reports and their discussions.",
        "按最近研究活动保留报告及其追问。",
      )}
    >
      <form
        className="preferences"
        onSubmit={(event) => {
          event.preventDefault();
          void action.run(async () => {
            const current = await api<{ count: number }>("/ai/storage");
            if (
              limit > 0 &&
              current.count > limit &&
              !window.confirm(
                t(
                  `Keep ${limit} reports and delete ${current.count - limit} older reports with their discussions?`,
                  `保留最近活动的 ${limit} 份报告，并删除其余 ${current.count - limit} 份及相关追问？`,
                ),
              )
            )
              return;
            await saveSettings({ ...user.settings, analysis_limit: limit });
            storage.reload();
            notify(t("Report storage updated", "报告存储设置已更新"));
          });
        }}
      >
        <label>
          {t("Maximum saved reports", "报告数量上限")}
          <input
            type="number"
            min={0}
            max={1000}
            required
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </label>
        <p className="field-hint">
          {t(
            "0 means unlimited. Active discussions are retained.",
            "0 表示不限。正在追问的报告会保留。",
          )}{" "}
          {t("Saved", "当前保存")}：{storage.data?.count ?? "—"}
        </p>
        <Button busy={action.busy}>
          {t("Save report limit", "保存报告上限")}
        </Button>
        {!!storage.error && (
          <ResourceError error={storage.error} retry={storage.reload} />
        )}
      </form>
    </Panel>
  );
}
