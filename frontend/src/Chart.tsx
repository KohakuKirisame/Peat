import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Check, CandlestickChart, RotateCcw } from "lucide-react";
import { date, num, put, useAction, useApp, useResource } from "./api";
import { Button, Empty, Loading, ResourceError, Tag } from "./ui";

type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};
type ChartData = {
  data: {
    symbol: string;
    name: string;
    currency: string;
    timezone: string;
    source: string;
    status: string;
    as_of: string;
    candles: Candle[];
  };
};
const ranges: Record<string, string[]> = {
  "1m": ["1d", "5d"],
  "5m": ["1d", "5d", "1mo"],
  "15m": ["5d", "1mo"],
  "1h": ["1mo", "3mo", "6mo", "1y"],
  "1d": ["1mo", "3mo", "6mo", "1y", "5y", "max"],
  "1wk": ["1y", "5y", "max"],
  "1mo": ["5y", "max"],
};
export function PriceChart({
  ticker,
  symbol: initialSymbol,
}: {
  ticker: string;
  symbol?: string;
}) {
  const { t, notify, user } = useApp();
  const [symbol, setSymbol] = useState(initialSymbol || ticker),
    [draft, setDraft] = useState(symbol);
  const [interval, setInterval] = useState("1d"),
    [period, setPeriod] = useState("3mo"),
    [hover, setHover] = useState<number | null>(null),
    [end, setEnd] = useState(0),
    [count, setCount] = useState(80);
  const request = useResource<ChartData>(
    symbol
      ? `/charts?symbol=${encodeURIComponent(symbol)}&interval=${interval}&period=${period}`
      : null,
    0,
    false,
  );
  const action = useAction(),
    data = request.data?.data,
    candles = data?.candles || [];
  useEffect(() => {
    setSymbol(initialSymbol || ticker);
    setDraft(initialSymbol || ticker);
  }, [ticker, initialSymbol]);
  useEffect(() => {
    setEnd(candles.length);
    setHover(null);
  }, [request.data]);
  useEffect(() => {
    if (data?.symbol && symbol.includes("_"))
      setDraft((current) => (current === symbol ? data.symbol : current));
  }, [data?.symbol, symbol]);
  const visible = useMemo(
    () => candles.slice(Math.max(0, end - count), end),
    [candles, end, count],
  );
  const low = visible.length ? Math.min(...visible.map((c) => c.low)) : 0,
    high = visible.length ? Math.max(...visible.map((c) => c.high)) : 1,
    span = high - low || 1;
  const y = (v: number) => 260 - ((v - low) / span) * 215,
    x = (i: number) => 32 + ((i + 0.5) / Math.max(visible.length, 1)) * 820;
  const selected = visible[hover ?? visible.length - 1],
    maxVolume = Math.max(...visible.map((c) => c.volume || 0), 1);
  const label = (time: number) =>
    new Date(time * 1000).toLocaleString(
      user.settings.language === "zh" ? "zh-CN" : "en-GB",
      {
        month: "short",
        day: "numeric",
        ...(["1m", "5m", "15m", "1h"].includes(interval)
          ? { hour: "2-digit" as const, minute: "2-digit" as const }
          : {}),
        timeZone: data?.timezone || "UTC",
      },
    );
  return (
    <div className="price-chart">
      <div className="chart-controls">
        <div className="segmented intervals">
          {Object.keys(ranges).map((i) => (
            <button
              key={i}
              aria-pressed={interval === i}
              className={interval === i ? "active" : ""}
              onClick={() => {
                setInterval(i);
                if (!ranges[i].includes(period)) setPeriod(ranges[i][0]);
              }}
            >
              {
                {
                  "1m": t("1m", "1分"),
                  "5m": t("5m", "5分"),
                  "15m": t("15m", "15分"),
                  "1h": t("1h", "1时"),
                  "1d": t("1D", "日"),
                  "1wk": t("1W", "周"),
                  "1mo": t("1M", "月"),
                }[i]
              }
            </button>
          ))}
        </div>
        <select
          aria-label={t("Chart range", "行情范围")}
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
        >
          {ranges[interval].map((r) => (
            <option key={r} value={r}>
              {r === "max" ? t("All history", "全部历史") : r}
            </option>
          ))}
        </select>
      </div>
      <form
        className="symbol-form"
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            const normalized = draft.trim().toUpperCase();
            await put("/charts/mapping", {
              ticker,
              symbol: normalized,
            });
            setSymbol(normalized);
            setDraft(normalized);
            notify(t("Market symbol saved", "行情代码已保存"));
          });
        }}
      >
        <label htmlFor="market-symbol">{t("Market symbol", "行情代码")}</label>
        <input
          id="market-symbol"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={30}
          placeholder="AIR.PA / ASML.AS / VUSA.L"
        />
        <button
          type="submit"
          aria-label={t("Save market symbol", "保存行情代码")}
        >
          <Check size={16} />
        </button>
        <span className="muted small">
          {data?.name} {data?.symbol && `· ${data.symbol}`}{" "}
          {data?.currency && `· ${data.currency}`}{" "}
          {data?.timezone && `· ${data.timezone}`}
        </span>
      </form>
      {request.error ? (
        <ResourceError error={request.error} retry={request.reload} />
      ) : request.loading ? (
        <Loading />
      ) : !visible.length ? (
        <Empty
          icon={<CandlestickChart />}
          title={t("No price history", "暂无历史行情")}
        />
      ) : (
        <>
          <div className="ohlc">
            <span>{selected && label(selected.time)}</span>
            {selected &&
              (["open", "high", "low", "close"] as const).map((key, i) => (
                <span key={key}>
                  <em>
                    {
                      [t("O", "开"), t("H", "高"), t("L", "低"), t("C", "收")][
                        i
                      ]
                    }
                  </em>{" "}
                  <b
                    className={
                      selected.close >= selected.open ? "positive" : "negative"
                    }
                  >
                    {num(selected[key], 4)}
                  </b>
                </span>
              ))}
            <span>
              {t("Vol", "量")} {num(selected?.volume, 0)}
            </span>
          </div>
          <svg
            className="candles"
            viewBox="0 0 960 355"
            role="img"
            aria-label={t(
              `${symbol} candlestick price history`,
              `${symbol} K 线历史行情`,
            )}
            onPointerLeave={() => setHover(null)}
            onPointerMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const coord = ((e.clientX - rect.left) / rect.width) * 960;
              setHover(
                Math.max(
                  0,
                  Math.min(
                    visible.length - 1,
                    Math.floor(((coord - 32) / 820) * visible.length),
                  ),
                ),
              );
            }}
          >
            {[0, 0.25, 0.5, 0.75, 1].map((fraction, i) => (
              <g key={i}>
                <line
                  x1="28"
                  x2="860"
                  y1={y(low + span * fraction)}
                  y2={y(low + span * fraction)}
                  className="chart-grid"
                />
                <text x="880" y={y(low + span * fraction) + 4}>
                  {num(low + span * fraction, 3)}
                </text>
              </g>
            ))}
            {visible.map((c, i) => {
              const up = c.close >= c.open,
                w = Math.max(1, (820 / visible.length) * 0.62);
              return (
                <g key={c.time} className={up ? "candle-up" : "candle-down"}>
                  <line
                    x1={x(i)}
                    x2={x(i)}
                    y1={y(c.high)}
                    y2={y(c.low)}
                    strokeWidth="1.2"
                  />
                  <rect
                    x={x(i) - w / 2}
                    y={Math.min(y(c.open), y(c.close))}
                    width={w}
                    height={Math.max(1, Math.abs(y(c.open) - y(c.close)))}
                  />
                  <rect
                    x={x(i) - w / 2}
                    y={322 - ((c.volume || 0) / maxVolume) * 36}
                    width={w}
                    height={((c.volume || 0) / maxVolume) * 36}
                    opacity=".22"
                  />
                </g>
              );
            })}
            {Array.from(
              new Set([
                0,
                Math.floor(visible.length / 3),
                Math.floor((visible.length * 2) / 3),
                visible.length - 1,
              ]),
            ).map((i) => (
              <text
                key={i}
                x={x(i)}
                y="345"
                textAnchor={
                  i === 0
                    ? "start"
                    : i === visible.length - 1
                      ? "end"
                      : "middle"
                }
              >
                {label(visible[i].time)}
              </text>
            ))}
            {hover !== null && selected && (
              <g>
                <line
                  x1={x(hover)}
                  x2={x(hover)}
                  y1="30"
                  y2="324"
                  className="crosshair"
                />
                <line
                  x1="28"
                  x2="860"
                  y1={y(selected.close)}
                  y2={y(selected.close)}
                  className="crosshair"
                />
              </g>
            )}
          </svg>
          <div className="chart-bottom">
            <label>
              {t("History", "历史")}
              <input
                aria-label={t("Browse candle history", "浏览 K 线历史")}
                type="range"
                min={Math.min(count, candles.length)}
                max={candles.length}
                value={end}
                onChange={(e) => setEnd(+e.target.value)}
              />
            </label>
            <select
              aria-label={t("Visible candles", "可见 K 线数")}
              value={count}
              onChange={(e) => setCount(+e.target.value)}
            >
              {[40, 80, 160, 300].map((n) => (
                <option key={n} value={n}>
                  {n} {t("bars", "根")}
                </option>
              ))}
            </select>
            <button
              className="icon-button"
              onClick={() => setEnd(candles.length)}
              aria-label={t("Latest candles", "最新 K 线")}
            >
              <RotateCcw size={15} />
            </button>
          </div>
          <div className="source-line">
            <span>
              {data?.source} · {t("Provider OHLC", "行情源 OHLC")} ·{" "}
              {date(data?.as_of, user.settings.language)}
            </span>
            <Tag tone={data?.status === "stale" ? "amber" : ""}>
              {data?.status === "stale"
                ? t("Stale", "已过期")
                : t("May be delayed", "可能延迟")}
            </Tag>
          </div>
        </>
      )}
    </div>
  );
}
