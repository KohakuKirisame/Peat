import { useRef, useState } from "react";
import { NewsArticle } from "./NewsArticle";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Newspaper,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import {
  api,
  date,
  del,
  money,
  num,
  post,
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

export function News() {
  const { t, user } = useApp();
  const [q, setQ] = useState(""),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0);
  const r = useResource(
      `/news?q=${encodeURIComponent(search)}&offset=${offset}`,
    ),
    action = useAction();
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("THE SIGNAL IN THE HEADLINES", "关注新闻中的有效信息")}
          </div>
          <h1>{t("Newsroom", "新闻室")}</h1>
          <p>
            {t(
              "Company and industry news, collected around what you follow.",
              "围绕你的持仓及关注公司，汇集公司和行业新闻。",
            )}
          </p>
        </div>
        <Button
          busy={action.busy}
          onClick={() =>
            action.run(
              async () => {
                const result = await post("/news/sync");
                r.reload();
                if (result.errors?.length)
                  throw new Error("news_feed_unavailable");
              },
              t("News updated", "新闻已更新"),
            )
          }
        >
          <RefreshCw size={16} />
          {t("Collect news", "获取新闻")}
        </Button>
      </div>
      <div className="news-toolbar">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(q);
            setOffset(0);
          }}
          className="search-box"
        >
          <Search size={17} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t(
              "Search companies, topics or headlines…",
              "搜索公司、主题或标题…",
            )}
            aria-label={t("Search news", "搜索新闻")}
          />
          <button>{t("Search", "搜索")}</button>
        </form>
        <span className="muted small">
          {r.data?.total || 0} / {user.settings.news_limit}{" "}
          {t("saved", "条已保存")}
        </span>
        <button
          className="text-button danger"
          onClick={() => {
            if (
              window.confirm(t("Clear all saved news?", "清空所有已保存新闻？"))
            )
              void action.run(async () => {
                await del("/news");
                r.reload();
              });
          }}
        >
          <Trash2 size={15} />
          {t("Clear archive", "清空新闻")}
        </button>
      </div>
      {r.error ? (
        <ResourceError error={r.error} retry={r.reload} />
      ) : r.loading ? (
        <Loading />
      ) : (
        <Panel
          title={
            search
              ? t("Search results", "搜索结果")
              : t("Latest developments", "最新动态")
          }
          sub={t(
            "Headlines and excerpts · expand an article to read the saved body",
            "标题与摘要 · 展开查看本地保存的正文",
          )}
        >
          {r.data?.items?.length ? (
            <div className="news-feed">
              {r.data.items.map((n: any) => (
                <NewsArticle key={n.id} article={n} />
              ))}
            </div>
          ) : (
            <Empty
              icon={<Newspaper size={25} />}
              title={t("A fresh page", "新闻室已准备好")}
              body={t(
                "Collect news to bring the latest company and industry developments into your workspace.",
                "点击获取新闻，将公司和行业的最新动态保存到你的工作台。",
              )}
            />
          )}
        </Panel>
      )}
      <Pagination
        offset={offset}
        total={r.data?.total || 0}
        onChange={setOffset}
      />
      {r.data?.status && (
        <div className="source-line">
          <span>
            Google News RSS ·{" "}
            {date(r.data.status.updated_at, user.settings.language)}
          </span>
          <span>
            {t("Retention", "保存期限")} {user.settings.news_days}{" "}
            {t("days", "天")}
          </span>
        </div>
      )}
    </>
  );
}

export function Pagination({
  offset,
  total,
  onChange,
}: {
  offset: number;
  total: number;
  onChange: (n: number) => void;
}) {
  const { t } = useApp();
  return total > 50 ? (
    <div className="pagination">
      <Button
        secondary
        disabled={!offset}
        onClick={() => onChange(Math.max(0, offset - 50))}
      >
        <ArrowLeft size={16} />
        {t("Previous", "上一页")}
      </Button>
      <span>
        {offset + 1}–{Math.min(offset + 50, total)} / {total}
      </span>
      <Button
        secondary
        disabled={offset + 50 >= total}
        onClick={() => onChange(offset + 50)}
      >
        {t("Next", "下一页")}
        <ArrowRight size={16} />
      </Button>
    </div>
  ) : null;
}

export function History() {
  const { t, user } = useApp();
  const [kind, setKind] = useState("orders"),
    [offset, setOffset] = useState(0);
  const r = useResource(`/history?kind=${kind}&offset=${offset}`),
    portfolio = useResource("/portfolio"),
    action = useAction(),
    file = useRef<HTMLInputElement>(null);
  const next = r.data?.sync?.data?.next,
    complete = r.data?.sync?.data?.complete,
    summary = portfolio.data?.statement;
  async function importFile(f: File) {
    const form = new FormData();
    form.append("file", f);
    const result = await api("/statements", { method: "POST", body: form });
    portfolio.reload();
    return result;
  }
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("THE RECORD BEHIND THE NUMBERS", "数字背后的记录")}
          </div>
          <h1>{t("Activity & statements", "账户流水与对账单")}</h1>
          <p>
            {t(
              "Review historical fills, cash movements and dividend payments.",
              "查看历史成交、资金变动和股息记录。",
            )}
          </p>
        </div>
        <Button
          secondary
          onClick={() => file.current?.click()}
          busy={action.busy}
        >
          <Upload size={16} />
          {t("Import CSV", "导入 CSV")}
        </Button>
        <input
          type="file"
          ref={file}
          hidden
          accept=".csv,text/csv"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f)
              void action.run(
                () => importFile(f),
                t(
                  "Statement imported; duplicate rows skipped.",
                  "对账单已导入，重复记录已跳过。",
                ),
              );
            e.target.value = "";
          }}
        />
      </div>
      <Panel
        title={t("Transaction history", "交易历史")}
        sub={t(
          "History is loaded in provider pages of up to 50 records.",
          "按平台分页读取，每页最多 50 条。",
        )}
        action={
          <Button
            busy={action.busy}
            onClick={() =>
              action.run(
                async () => {
                  await post(
                    `/history/sync?kind=${kind}${next ? "&cursor=" + encodeURIComponent(next) : ""}`,
                  );
                  r.reload();
                },
                t("History page synchronized", "历史分页已同步"),
              )
            }
          >
            <RefreshCw size={15} />
            {next
              ? t("Load older history", "读取更早历史")
              : complete
                ? t("Refresh latest", "刷新最新记录")
                : t("Sync history", "同步历史")}
          </Button>
        }
      >
        <div className="tabs">
          {[
            ["orders", t("Executions", "成交记录")],
            ["dividends", t("Dividends", "股息")],
            ["transactions", t("Cash movements", "资金流水")],
          ].map(([key, label]) => (
            <button
              key={key}
              className={kind === key ? "active" : ""}
              onClick={() => {
                setKind(key);
                setOffset(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {r.error ? (
          <ResourceError error={r.error} retry={r.reload} />
        ) : r.loading ? (
          <Loading />
        ) : r.data?.items?.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("Date", "日期")}</th>
                  <th>{t("Asset / type", "资产 / 类型")}</th>
                  <th>{t("Quantity", "数量")}</th>
                  <th>{t("Amount", "金额")}</th>
                  <th>{t("Realized P&L", "已实现盈亏")}</th>
                </tr>
              </thead>
              <tbody>
                {r.data.items.map((row: any, i: number) => {
                  const fill = row.fill || {},
                    order = row.order || {},
                    wallet = fill.walletImpact || {};
                  return (
                    <tr key={i}>
                      <td>
                        {date(
                          fill.filledAt || row.paidOn || row.dateTime,
                          user.settings.language,
                        )}
                      </td>
                      <td>
                        <strong>
                          {order.instrument?.name ||
                            row.instrument?.name ||
                            row.type ||
                            order.ticker}
                        </strong>
                        <small>
                          {order.side || row.ticker || row.reference}
                        </small>
                      </td>
                      <td>{num(fill.quantity ?? row.quantity, 6)}</td>
                      <td>
                        {money(
                          wallet.netValue ?? row.amount,
                          wallet.currency || row.currency,
                          user.settings.language,
                        )}
                      </td>
                      <td
                        className={
                          wallet.realisedProfitLoss >= 0
                            ? "positive"
                            : "negative"
                        }
                      >
                        {money(
                          wallet.realisedProfitLoss,
                          wallet.currency,
                          user.settings.language,
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={t("A history you can trace", "可追溯的账户历史")}
            body={t(
              "Connect Trading 212 and sync your history to see records here.",
              "连接 Trading 212 并同步历史后，在这里查看记录。",
            )}
          />
        )}
        <div className="panel-foot">
          {r.data?.total || 0} {t("records saved", "条已保存")} ·{" "}
          {complete
            ? t(
                "Provider history fully paged at the last sync",
                "上次同步已读取到历史末页",
              )
            : t("Historical coverage may be partial", "当前历史记录可能不完整")}
        </div>
      </Panel>
      <Pagination
        offset={offset}
        total={r.data?.total || 0}
        onChange={setOffset}
      />
      <Panel
        title={t("Statement summary", "对账单汇总")}
        sub={t(
          "Imported English Trading 212 CSVs · amounts kept in their original currencies",
          "导入英文版 Trading 212 CSV · 按原始币种分别汇总",
        )}
        action={
          summary?.rows > 0 ? (
            <button
              className="text-button danger"
              onClick={() => {
                if (
                  window.confirm(
                    t(
                      "Remove all imported statement rows?",
                      "清除所有导入的对账单记录？",
                    ),
                  )
                )
                  void action.run(async () => {
                    await del("/statements");
                    portfolio.reload();
                  });
              }}
            >
              <Trash2 size={15} />
              {t("Clear", "清除")}
            </button>
          ) : null
        }
      >
        {summary?.rows ? (
          <>
            <div className="statement-meta">
              {summary.rows} {t("rows", "行")} · {summary.from} — {summary.to}
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t("Currency", "币种")}</th>
                    <th>{t("Deposits", "入金")}</th>
                    <th>{t("Withdrawals", "出金")}</th>
                    <th>{t("Net deposits", "净入金")}</th>
                    <th>{t("Realized P&L", "已实现盈亏")}</th>
                    <th>{t("Dividends", "股息")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.currencies).map(
                    ([currency, amounts]: [string, any]) => (
                      <tr key={currency}>
                        <td>{currency}</td>
                        {[
                          "deposits",
                          "withdrawals",
                          "net_deposits",
                          "realized",
                          "dividends",
                        ].map((k) => (
                          <td key={k}>
                            {money(
                              amounts[k],
                              currency,
                              user.settings.language,
                            )}
                          </td>
                        ))}
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
            <div className="panel-foot">
              {t(
                "Covers imported rows only. This summary is separate from the live account totals.",
                "仅汇总已导入记录，独立于实时账户汇总。",
              )}
            </div>
          </>
        ) : (
          <Empty
            icon={<ArrowDownToLine size={23} />}
            title={t("Add the historical picture", "补充历史数据")}
            body={t(
              "Import an account CSV to review net deposits, realized P&L and dividends for its covered period.",
              "导入账户 CSV，查看对应期间的净入金、已实现收益和股息。",
            )}
          />
        )}
      </Panel>
    </>
  );
}
