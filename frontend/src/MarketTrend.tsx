import { useId, useMemo, useState } from "react";
import { num, useApp } from "./api";
import { Sparkline } from "./ui";

type Observation = { date: string; value: number };

export function MarketTrend({
  quote,
  color,
}: {
  quote: {
    name: string;
    kind: string;
    unit: string;
    timezone?: string;
    observations?: Observation[];
    series?: number[];
  };
  color: string;
}) {
  const { t, user } = useApp();
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const points = useMemo(
    () =>
      (quote.observations || [])
        .filter(
          (p) =>
            Number.isFinite(p.value) && Number.isFinite(Date.parse(p.date)),
        )
        .slice()
        .sort((a, b) => Date.parse(a.date) - Date.parse(b.date)),
    [quote.observations],
  );
  if (!points.length)
    return <Sparkline values={quote.series || []} color={color} />;
  const selectedIndex = Math.min(
    active ?? points.length - 1,
    points.length - 1,
  );
  const selected = points[selectedIndex];
  const min = Math.min(...points.map((p) => p.value));
  const span = Math.max(...points.map((p) => p.value)) - min || 1;
  const x = (i: number) =>
    points.length === 1 ? 65 : 3 + (i / (points.length - 1)) * 124;
  const y = (value: number) => 30 - ((value - min) / span) * 26;
  const label = (point: Observation) => {
    const daily = quote.kind === "yield";
    const at = daily
      ? new Date(`${point.date.slice(0, 10)}T12:00:00Z`)
      : new Date(point.date);
    return at.toLocaleString(
      user.settings.language === "zh" ? "zh-CN" : "en-GB",
      {
        year: "numeric",
        month: "short",
        day: "numeric",
        ...(daily
          ? {}
          : ({
              hour: "2-digit",
              minute: "2-digit",
              timeZoneName: "short",
            } as const)),
        timeZone: daily ? "UTC" : quote.timezone || "UTC",
      },
    );
  };
  const select = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const coordinate = ((event.clientX - rect.left) / rect.width) * 130;
    setActive(
      Math.max(
        0,
        Math.min(
          points.length - 1,
          Math.round(((coordinate - 3) / 124) * (points.length - 1)),
        ),
      ),
    );
  };
  return (
    <div className="market-trend">
      <svg
        viewBox="0 0 130 34"
        preserveAspectRatio="none"
        role="slider"
        tabIndex={0}
        aria-label={`${quote.name} · ${t("History", "历史曲线")}`}
        aria-valuemin={0}
        aria-valuemax={points.length - 1}
        aria-valuenow={selectedIndex}
        aria-valuetext={`${label(selected)} · ${num(selected.value, 4)} ${quote.unit}`}
        aria-describedby={active !== null ? id : undefined}
        onPointerMove={select}
        onPointerDown={select}
        onPointerLeave={(e) => {
          if (e.pointerType !== "touch") setActive(null);
        }}
        onFocus={() => setActive((current) => current ?? points.length - 1)}
        onBlur={() => setActive(null)}
        onKeyDown={(e) => {
          if (
            ["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(e.key)
          ) {
            e.preventDefault();
            if (e.key === "Escape") setActive(null);
            else
              setActive(
                e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? points.length - 1
                    : Math.max(
                        0,
                        Math.min(
                          points.length - 1,
                          selectedIndex + (e.key === "ArrowLeft" ? -1 : 1),
                        ),
                      ),
              );
          }
        }}
      >
        <path
          d={points
            .map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.value)}`)
            .join(" ")}
          fill="none"
          stroke={color}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {(active !== null || points.length === 1) && (
          <g>
            <line
              x1={x(selectedIndex)}
              x2={x(selectedIndex)}
              y1="1"
              y2="33"
              className="crosshair"
            />
            <circle
              cx={x(selectedIndex)}
              cy={y(selected.value)}
              r="2.8"
              fill={color}
            />
          </g>
        )}
      </svg>
      {active !== null && (
        <div id={id} role="tooltip" className="market-trend-tooltip">
          <time dateTime={selected.date}>{label(selected)}</time>
          <strong>
            {num(selected.value, 4)} <span>{quote.unit}</span>
          </strong>
        </div>
      )}
    </div>
  );
}
