import { useEffect, useState } from "react";
import { date, num, useApp } from "./api";
import { External, Tag } from "./ui";

export function DataStamp({ evidence }: { evidence: any }) {
  const { t, user } = useApp();
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);
  const fresh = evidence?.freshness;
  if (!fresh) return null;
  const minutes = Math.max(
    0,
    Math.floor((clock - Date.parse(fresh.collected_at)) / 60000),
  );
  const checks = (evidence.research_activity?.market_calls || []).filter(
    (call: any) => call.tool === "get_quote" && call.result?.retrieved_at,
  );
  const last = checks.at(-1)?.result;
  return (
    <div className="research-datastamp">
      <Tag>
        {fresh.mode === "live_refresh"
          ? t("Latest-data check", "最新数据核验")
          : t("Saved evidence", "已有资料")}
      </Tag>
      <span>
        {t("Collected", "资料获取")} ·{" "}
        {date(fresh.collected_at, user.settings.language)} ·{" "}
        {Number.isFinite(minutes) ? `${minutes} ${t("min ago", "分钟前")}` : ""}
      </span>
      {last && (
        <span>
          {t("Last quote check", "最近查价")} ·{" "}
          {date(last.retrieved_at, user.settings.language)}
        </span>
      )}
    </div>
  );
}

export function ResearchSources({
  evidence,
  activity,
}: {
  evidence: any;
  activity?: any;
}) {
  const { t, user } = useApp();
  const trace = activity || evidence?.research_activity || {};
  if (!evidence?.freshness && !activity && !evidence?.research_activity)
    return null;
  const quotes = new Map<string, any>();
  for (const asset of evidence?.price_histories || [])
    if (asset.quote)
      quotes.set(asset.symbol || asset.ticker, {
        ...asset.quote,
        symbol: asset.symbol || asset.ticker,
        status: asset.status,
      });
  for (const call of trace.market_calls || [])
    if (
      call.tool === "get_quote" &&
      call.result?.symbol &&
      call.result.price != null
    )
      quotes.set(call.result.symbol, call.result);
  const sessions: Record<string, string> = {
    pre: t("Pre-market", "盘前"),
    regular: t("Regular", "常规"),
    post: t("After-hours", "盘后"),
    unknown: "—",
  };
  return (
    <div className="research-sources">
      {quotes.size > 0 && (
        <div className="markdown-table">
          <table>
            <thead>
              <tr>
                <th>{t("Instrument", "标的")}</th>
                <th>{t("Reference quote", "来源报价")}</th>
                <th>{t("Quote time (local)", "报价时间（本地）")}</th>
                <th>{t("Session", "时段")}</th>
              </tr>
            </thead>
            <tbody>
              {Array.from(quotes.values()).map((q) => (
                <tr key={q.symbol}>
                  <td>{q.symbol}</td>
                  <td>
                    {num(q.price, 4)} {q.currency}
                    {q.status === "stale" && (
                      <Tag tone="amber">{t("Cached", "旧缓存")}</Tag>
                    )}
                  </td>
                  <td>
                    <time dateTime={q.as_of}>
                      {date(q.as_of, user.settings.language)}
                    </time>
                  </td>
                  <td>{sessions[q.session] || q.session}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {trace.web_searches?.length > 0 && (
        <p>
          {t("Web searches", "联网检索")} · {trace.web_searches.length}
        </p>
      )}
      {trace.market_calls?.length > 0 && (
        <p>
          {t("Market/news checks", "行情与新闻查询")} ·{" "}
          {trace.market_calls.length}
        </p>
      )}
      {trace.market_tools_status === "provider_unsupported" && (
        <p className="field-hint">
          {t(
            "This provider did not accept tool calls; the refreshed evidence was used.",
            "此接口不支持工具调用，本次使用已刷新的资料。",
          )}
        </p>
      )}
      {(trace.web_searches || []).map((search: any, i: number) => (
        <p key={i} className="source-line">
          {search.query ||
            search.queries?.join(" · ") ||
            t("Web source lookup", "网页资料查询")}
          {search.url && (
            <External href={search.url}>{t("Source", "来源")}</External>
          )}
        </p>
      ))}
      {evidence?.price_coverage?.omitted_symbols?.length > 0 && (
        <p className="field-hint">
          {t(
            "Additional instruments available to query",
            "可按需继续查询的标的",
          )}
          ：{evidence.price_coverage.omitted_symbols.join(", ")}
        </p>
      )}
      {evidence?.price_coverage?.available_assets <
        evidence?.price_coverage?.prepared_assets && (
        <p className="field-hint">
          {t("Quotes retrieved", "已取得报价")} ·{" "}
          {evidence.price_coverage.available_assets}/
          {evidence.price_coverage.prepared_assets}
        </p>
      )}
      {(evidence?.news || []).map((news: any) => (
        <div className="news-timing" key={news.id}>
          <External href={news.url}>{news.title}</External>
          <div className="field-hint">
            [news {news.id}] ·{" "}
            {news.publication_precision === "date"
              ? news.effective_published_at?.slice(0, 10)
              : date(
                  news.effective_published_at || news.published_at,
                  user.settings.language,
                )}{" "}
            ·{" "}
            {news.timing_class === "background"
              ? t("Historical background", "历史背景")
              : news.timing_class === "undated"
                ? t("Publication date unverified", "发表时间待核实")
                : t("Recent publication", "近期发表")}
          </div>
          {(news.price_context || []).map((context: any, i: number) => (
            <p className="field-hint" key={i}>
              {context.symbol} ·{" "}
              {context.status === "matched" ? (
                <>
                  {context.basis === "publication_time"
                    ? t("Around publication", "发表前后")
                    : t("Daily session context", "按交易日对齐")}{" "}
                  ·{" "}
                  {context.before &&
                    `${context.before.time ? date(context.before.time, user.settings.language) : context.before.session_date}: ${num(context.before.price, 4)}`}{" "}
                  →{" "}
                  {context.first_after || context.next_session
                    ? `${(context.first_after || context.next_session).time ? date((context.first_after || context.next_session).time, user.settings.language) : (context.first_after || context.next_session).session_date}: ${num((context.first_after || context.next_session).price, 4)}`
                    : "—"}
                </>
              ) : (
                t("No matching price window", "未取得对应时间窗口")
              )}
            </p>
          ))}
        </div>
      ))}
    </div>
  );
}
