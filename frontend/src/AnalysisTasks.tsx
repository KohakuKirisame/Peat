import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  LoaderCircle,
  Square,
  X,
} from "lucide-react";
import { api, errorMessage, post, useApp } from "./api";
import { Button } from "./ui";

export type AnalysisJob = {
  id: string;
  status: string;
  phase: string;
  model: string;
  provider: string;
  reasoning_effort: string;
  style: string;
  analysis_id: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};
const running = (job: AnalysisJob | null) =>
  !!job && ["queued", "running", "cancelling"].includes(job.status);
const Tasks = createContext<{
  job: AnalysisJob | null;
  active: boolean;
  starting: boolean;
  stopping: boolean;
  hidden: boolean;
  start: () => Promise<void>;
  cancel: () => Promise<void>;
  dismiss: () => void;
}>({} as never);
export const useAnalysisTask = () => useContext(Tasks);

export function AnalysisTasks({ children }: { children: ReactNode }) {
  const { user, t, notify } = useApp();
  const [job, setJob] = useState<AnalysisJob | null>(null),
    [starting, setStarting] = useState(false),
    [stopping, setStopping] = useState(false);
  const [dismissed, setDismissed] = useState(
    sessionStorage.getItem(`peat-hidden-job-${user.id}`),
  );
  const revision = useRef(0),
    latest = useRef<AnalysisJob | null>(null),
    alive = useRef(true),
    wake = useRef<() => void>(() => {});
  const display = useRef({ t, notify });
  display.current = { t, notify };
  const accept = (next: AnalysisJob | null) => {
    const previous = latest.current;
    if (
      previous &&
      previous.id === next?.id &&
      running(previous) &&
      next?.status === "completed"
    )
      display.current.notify(
        display.current.t("Research brief is ready", "研究简报已生成"),
      );
    latest.current = next;
    setJob(next);
  };
  useEffect(() => {
    alive.current = true;
    let disposed = false,
      inFlight = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (disposed || inFlight) return;
      inFlight = true;
      const version = revision.current;
      if (document.visibilityState !== "hidden") {
        try {
          const next = await api<AnalysisJob | null>("/ai/jobs/current");
          if (!disposed && version === revision.current)
            accept(next?.id ? next : null);
        } catch {
          /* A reconnect or next poll recovers status; the server task continues. */
        }
      }
      inFlight = false;
      if (!disposed)
        timer = setTimeout(poll, running(latest.current) ? 1500 : 10000);
    };
    wake.current = () => {
      clearTimeout(timer);
      void poll();
    };
    const visible = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        void poll();
      }
    };
    void poll();
    document.addEventListener("visibilitychange", visible);
    return () => {
      alive.current = false;
      disposed = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [user.id]);
  async function start() {
    setStarting(true);
    revision.current++;
    try {
      const next = await post<AnalysisJob>("/ai/analyze");
      if (alive.current) {
        accept(next);
        setDismissed(null);
        wake.current();
      }
    } finally {
      if (alive.current) setStarting(false);
    }
  }
  async function cancel() {
    if (!latest.current || !running(latest.current)) return;
    setStopping(true);
    revision.current++;
    try {
      const next = await post<AnalysisJob>(
        `/ai/jobs/${latest.current.id}/cancel`,
      );
      if (alive.current) {
        accept(next);
        wake.current();
      }
    } finally {
      if (alive.current) setStopping(false);
    }
  }
  function dismiss() {
    if (job) {
      setDismissed(job.id);
      sessionStorage.setItem(`peat-hidden-job-${user.id}`, job.id);
    }
  }
  return (
    <Tasks.Provider
      value={{
        job,
        active: running(job),
        starting,
        stopping,
        hidden: job?.id === dismissed,
        start,
        cancel,
        dismiss,
      }}
    >
      {children}
    </Tasks.Provider>
  );
}

export function AnalysisTaskBanner({
  navigate,
}: {
  navigate: (page: string) => void;
}) {
  const { t, notify } = useApp(),
    task = useAnalysisTask();
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!task.active) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [task.active]);
  if (!task.job || (!task.active && task.hidden)) return null;
  const job = task.job,
    seconds = Math.max(
      0,
      Math.floor(
        ((job.finished_at ? Date.parse(job.finished_at) : clock) -
          Date.parse(job.created_at)) /
          1000,
      ),
    );
  const elapsed =
    seconds >= 3600
      ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
      : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const phases: Record<string, string> = {
    queued: t("Queued", "等待开始"),
    preparing: t("Preparing research", "准备研究数据"),
    fetching_news: t("Reading relevant news", "读取相关新闻"),
    generating: t("Generating brief", "正在生成简报"),
  };
  const title =
    job.status === "cancelling"
      ? t("Stopping generation…", "正在中止生成…")
      : task.active
        ? phases[job.phase] || t("Research running", "研究进行中")
        : job.status === "completed"
          ? t("Research brief is ready", "研究简报已生成")
          : job.status === "cancelled"
            ? t("Generation stopped", "生成已中止")
            : job.status === "interrupted"
              ? t(
                  "Generation was interrupted by a server restart",
                  "服务重启，生成已中断",
                )
              : t("Generation failed", "生成失败");
  return (
    <div className={`analysis-task-banner ${job.status}`} role="status">
      {task.active ? (
        <LoaderCircle size={19} className="spin" />
      ) : job.status === "completed" ? (
        <CheckCircle2 size={19} />
      ) : (
        <Square size={17} />
      )}
      <div className="analysis-task-copy">
        <strong>{title}</strong>
        <span>
          {job.model} · {job.reasoning_effort} · {elapsed}
          {task.active &&
            ` · ${t("Continues in the background", "可继续操作其他页面")}`}
          {job.status === "failed" &&
            job.error &&
            ` · ${errorMessage(new Error(job.error), t)}`}
        </span>
      </div>
      <div className="analysis-task-actions">
        {task.active ? (
          <Button
            secondary
            busy={task.stopping || job.status === "cancelling"}
            onClick={() =>
              task.cancel().catch((e) => notify(errorMessage(e, t), true))
            }
          >
            <Square size={13} />
            {t("Stop generation", "中止生成")}
          </Button>
        ) : (
          job.status === "completed" && (
            <Button
              secondary
              onClick={() => {
                navigate("intelligence");
                task.dismiss();
              }}
            >
              {t("View brief", "查看简报")}
              <ArrowUpRight size={14} />
            </Button>
          )
        )}
        {!task.active && (
          <button
            className="icon-button"
            aria-label={t("Dismiss task status", "关闭任务提示")}
            onClick={task.dismiss}
          >
            <X size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
