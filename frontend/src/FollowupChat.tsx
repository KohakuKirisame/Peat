import { useEffect, useRef, useState } from "react";
import { ChevronDown, MessageCircle, Send, Square } from "lucide-react";
import { api, date, errorMessage, useAction, useApp, useResource } from "./api";
import type { Settings } from "./api";
import { useAnalysisTask } from "./AnalysisTasks";
import { Markdown } from "./Markdown";
import { ModelControls } from "./ModelControls";
import { Button, Loading, Panel, ResourceError, Tag } from "./ui";

type Turn = {
  id: number;
  job_id: string;
  question: string;
  answer: string | null;
  provider: "openai" | "codex";
  model: string;
  reasoning_effort: string;
  status: string;
  error: string | null;
  created_at: string;
  answered_at: string | null;
  included_turns: number;
  omitted_turns: number;
};
type Page = { items: Turn[]; next_before: number | null };

const requestId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");

export function FollowupChat({ analysis }: { analysis: any }) {
  const { user, t, notify } = useApp();
  const task = useAnalysisTask();
  const mine =
    task.job?.kind === "followup" && task.job.analysis_id === analysis.id;
  const path = `/ai/analyses/${analysis.id}/followups`;
  const resource = useResource<Page>(path, 0, false);
  const [turns, setTurns] = useState<Record<number, Turn>>({});
  const [before, setBefore] = useState<number | null | undefined>();
  const [question, setQuestion] = useState("");
  const [models, setModels] = useState<Settings>({
    ...user.settings,
    ai_provider: analysis.provider || user.settings.ai_provider,
    ai_model: analysis.model || user.settings.ai_model,
    reasoning_effort: analysis.reasoning_effort || "auto",
  });
  const submit = useAction(),
    older = useAction();
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!resource.data) return;
    const nearBottom =
      !list.current ||
      list.current.scrollHeight -
        list.current.scrollTop -
        list.current.clientHeight <
        70;
    setTurns((current) =>
      Object.assign(
        {},
        current,
        Object.fromEntries(
          (resource.data?.items || []).map((turn) => [turn.id, turn]),
        ),
      ),
    );
    setBefore((current) =>
      current === undefined ? (resource.data?.next_before ?? null) : current,
    );
    if (nearBottom)
      requestAnimationFrame(() => {
        if (list.current) list.current.scrollTop = list.current.scrollHeight;
      });
  }, [resource.data]);
  useEffect(() => {
    resource.reload();
  }, [task.job?.id, task.job?.status]);
  const history = Object.values(turns).sort((a, b) => a.id - b.id);
  const statuses: Record<string, string> = {
    queued: t("Queued", "等待回复"),
    running: t("Replying…", "回复中…"),
    cancelling: t("Stopping…", "正在中止…"),
    cancelled: t("Reply stopped", "回复已中止"),
    interrupted: t("Interrupted by a server restart", "服务重启，回复已中断"),
    failed: t("Reply failed", "回复失败"),
  };
  async function send() {
    const text = question.trim();
    if (!text || task.active || task.starting || submit.busy) return;
    const body = {
      question: text,
      provider: models.ai_provider,
      model: models.ai_model,
      reasoning_effort: models.reasoning_effort,
    };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature)
      pending.current = { signature, id: requestId() };
    await task.start(path, { ...body, request_id: pending.current.id });
    setQuestion((current) => (current.trim() === text ? "" : current));
    pending.current = null;
    resource.reload();
  }
  return (
    <Panel
      title={t("Discuss this brief", "追问这份简报")}
      sub={t(
        "Continue with this report and its saved evidence.",
        "结合这份报告及其保存的证据继续讨论。",
      )}
      className="followup-panel"
      action={<MessageCircle size={19} />}
    >
      {before && (
        <div className="followup-older">
          <Button
            secondary
            busy={older.busy}
            onClick={() =>
              older.run(async () => {
                const page = await api<Page>(`${path}?before=${before}`);
                setTurns((current) =>
                  Object.assign(
                    {},
                    current,
                    Object.fromEntries(
                      page.items.map((turn) => [turn.id, turn]),
                    ),
                  ),
                );
                setBefore(page.next_before);
              })
            }
          >
            {t("Load earlier questions", "查看更早追问")}
          </Button>
        </div>
      )}
      <div
        className="followup-history"
        ref={list}
        aria-label={t("Report discussion", "报告对话")}
      >
        {resource.loading && !history.length ? (
          <Loading />
        ) : (
          history.map((turn) => (
            <article className="followup-turn" key={turn.id}>
              <div className="followup-question">
                <span>
                  {t("You", "你")} ·{" "}
                  {date(turn.created_at, user.settings.language)}
                </span>
                <p>{turn.question}</p>
              </div>
              <div className="followup-answer">
                <div className="followup-meta">
                  <strong>Peat</strong>
                  <span>
                    {turn.model} · {turn.reasoning_effort}
                  </span>
                </div>
                {turn.answer && turn.status === "completed" ? (
                  <>
                    <Markdown content={turn.answer} />
                    {turn.omitted_turns > 0 && (
                      <p className="field-hint">
                        {t(
                          `This reply used the report and the latest ${turn.included_turns} completed turns.`,
                          `本次回复使用原报告及最近 ${turn.included_turns} 轮完整对话。`,
                        )}
                      </p>
                    )}
                  </>
                ) : (
                  <div className="followup-state">
                    <Tag tone={turn.status === "failed" ? "amber" : ""}>
                      {statuses[turn.status] || turn.status}
                    </Tag>
                    {turn.error && (
                      <p>{errorMessage(new Error(turn.error), t)}</p>
                    )}
                    {["failed", "cancelled", "interrupted"].includes(
                      turn.status,
                    ) && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setQuestion(turn.question);
                          setModels((current) => ({
                            ...current,
                            ai_provider: turn.provider,
                            ai_model: turn.model,
                            reasoning_effort: turn.reasoning_effort,
                          }));
                          input.current?.focus();
                        }}
                      >
                        {t("Ask again", "重新提问")}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))
        )}
      </div>
      {!!resource.error && (
        <ResourceError error={resource.error} retry={resource.reload} />
      )}
      <div className="followup-composer">
        {!history.length && (
          <div className="followup-suggestions">
            {[
              t("Why this allocation?", "为什么建议这样的仓位？"),
              t(
                "What would trigger a reduction or exit?",
                "什么条件下应减持或平仓？",
              ),
              t(
                "Which catalyst matters most for this holding period?",
                "这个持有周期应优先关注什么催化？",
              ),
            ].map((text) => (
              <button
                key={text}
                type="button"
                onClick={() => {
                  setQuestion(text);
                  input.current?.focus();
                }}
              >
                {text}
              </button>
            ))}
          </div>
        )}
        <details className="followup-models">
          <summary>
            {t("Reply model & reasoning", "回复模型与思考强度")} ·{" "}
            {models.ai_model || t("Choose a model", "选择模型")} ·{" "}
            {models.reasoning_effort}
            <ChevronDown size={14} />
          </summary>
          <ModelControls settings={models} onChange={setModels} />
        </details>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit.run(send);
          }}
        >
          <label htmlFor={`followup-question-${analysis.id}`}>
            {t("Follow-up question", "追问内容")}
          </label>
          <textarea
            id={`followup-question-${analysis.id}`}
            ref={input}
            rows={3}
            maxLength={8000}
            value={question}
            placeholder={t(
              "Ask about the reasoning, sizing or next steps…",
              "继续询问判断依据、仓位或下一步操作…",
            )}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                (event.ctrlKey || event.metaKey) &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <div className="followup-actions">
            <span className="field-hint">
              {task.active
                ? mine
                  ? t("Replying in the background", "正在后台回复")
                  : t(
                      "Wait for the current research task to finish",
                      "等待当前研究任务完成",
                    )
                : t("Ctrl / ⌘ + Enter to send", "Ctrl / ⌘ + Enter 发送")}
            </span>
            <div>
              {mine && task.active && (
                <Button
                  type="button"
                  secondary
                  busy={task.stopping || task.job?.status === "cancelling"}
                  onClick={() =>
                    task
                      .cancel()
                      .catch((error) => notify(errorMessage(error, t), true))
                  }
                >
                  <Square size={13} />
                  {t("Stop reply", "中止回复")}
                </Button>
              )}
              <Button
                busy={submit.busy || task.starting}
                disabled={task.active || !question.trim() || !models.ai_model}
                type="submit"
              >
                <Send size={14} />
                {t("Send question", "发送追问")}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </Panel>
  );
}
