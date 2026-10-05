import { ArrowUpRight, Inbox, LoaderCircle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { errorMessage, useApp } from "./api";

export function Button({
  children,
  busy = false,
  secondary = false,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  busy?: boolean;
  secondary?: boolean;
}) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className={`button ${secondary ? "secondary" : ""} ${className}`}
    >
      {busy && <LoaderCircle size={16} className="spin" />}
      {children}
    </button>
  );
}
export function Empty({
  title,
  body,
  action,
  icon,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon || <Inbox size={25} />}</div>
      <h3>{title}</h3>
      {body && <p>{body}</p>}
      {action}
    </div>
  );
}
export function Panel({
  title,
  sub,
  action,
  children,
  className = "",
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {sub && <p>{sub}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function ResourceError({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  const { t } = useApp();
  return (
    <div className="error-inline" role="alert">
      <span>{errorMessage(error, t)}</span>
      <button onClick={retry} aria-label={t("Retry", "重试")}>
        <RefreshCw size={16} />
      </button>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle className="spin" size={20} />
    </div>
  );
}
export function Tag({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`tag ${tone}`}>{children}</span>;
}
export function External({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a
      className="external"
      href={/^https?:\/\//.test(href) ? href : "#"}
      target="_blank"
      rel="noreferrer"
    >
      {children}
      <ArrowUpRight size={13} />
    </a>
  );
}
export function Sparkline({
  values,
  color = "var(--accent)",
  height = 34,
}: {
  values: number[];
  color?: string;
  height?: number;
}) {
  if (values.length < 2) return <span className="no-series">—</span>;
  const min = Math.min(...values),
    max = Math.max(...values),
    span = max - min || 1;
  return (
    <svg
      viewBox={`0 0 130 ${height}`}
      className="sparkline"
      role="img"
      aria-label="Price trend"
    >
      <path
        d={values
          .map(
            (n, i) =>
              `${i ? "L" : "M"}${(i / (values.length - 1)) * 128 + 1},${height - 3 - ((n - min) / span) * (height - 6)}`,
          )
          .join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
