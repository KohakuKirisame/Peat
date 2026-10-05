import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Cable,
  ChartNoAxesCombined,
  ChevronDown,
  CircleDollarSign,
  Plus,
  RefreshCw,
  Sprout,
  Trash2,
  Wallet,
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
  Sparkline,
  Tag,
} from "./ui";
import { PriceChart } from "./Chart";
import { HoldingsTable } from "./HoldingsTable";
import { NewsArticle } from "./NewsArticle";

export function MarketsPanel({ full = false }: { full?: boolean }) {
  const { t, user } = useApp();
  const r = useResource("/markets", 60000);
  const quotes = r.data?.data?.quotes || [],
    exchanges = r.data?.exchanges || [];
  return (
    <>
      <Panel
        title={t("Market pulse", "市场脉搏")}
        sub={t("Rates, energy & precious metals", "利率、能源与贵金属")}
        action={
          <button
            className="icon-button"
            aria-label={t("Refresh markets", "刷新行情")}
            onClick={r.reload}
          >
            <RefreshCw size={16} />
          </button>
        }
      >
        {r.error ? (
          <ResourceError error={r.error} retry={r.reload} />
        ) : r.loading && !r.data ? (
          <Loading />
        ) : (
          <div className={`market-grid ${full ? "expanded" : ""}`}>
            {quotes.map((q: any) => (
              <div className="market-quote" key={q.symbol}>
                <div className="quote-top">
                  <span>
                    {(
                      {
                        "US 2Y Treasury": t("US 2Y Treasury", "美债 2 年"),
                        "US 10Y Treasury": t("US 10Y Treasury", "美债 10 年"),
                        "US 30Y Treasury": t("US 30Y Treasury", "美债 30 年"),
                        "WTI crude": t("WTI crude", "WTI 原油"),
                        "Brent crude": t("Brent crude", "布伦特原油"),
                        "Natural gas": t("Natural gas", "天然气"),
                        Gold: t("Gold", "黄金"),
                        Silver: t("Silver", "白银"),
                        Platinum: t("Platinum", "铂金"),
                      } as Record<string, string>
                    )[q.name] || q.name}
                  </span>
                  <span
                    className={`tiny-dot ${q.status === "unavailable" || q.status === "stale" ? "amber" : ""}`}
                  />
                </div>
                <div className="quote-value">
                  {num(q.value)}
                  <span>{q.unit === "%" ? "%" : q.unit}</span>
                </div>
                <div className="quote-bottom">
                  <span className={q.change_pct >= 0 ? "positive" : "negative"}>
                    {q.change_pct == null
                      ? t(
                          q.kind === "yield" ? "Daily rate" : "Futures",
                          q.kind === "yield" ? "日度收益率" : "期货",
                        )
                      : `${q.change_pct >= 0 ? "+" : ""}${num(q.change_pct)}%`}
                  </span>
                  <Sparkline
                    values={q.series || []}
                    color={q.change_pct < 0 ? "var(--red)" : "var(--accent)"}
                  />
                </div>
                <div className="quote-source">
                  {q.source} ·{" "}
                  {q.status === "unavailable"
                    ? t("Unavailable", "暂不可用")
                    : q.status === "stale"
                      ? t("Stale", "已过期")
                      : q.as_of?.slice(0, 10)}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="panel-foot">
          {t(
            "Treasury: daily published rates. Commodities: delayed futures quotes.",
            "美债为日度公布收益率；大宗商品为可能延迟的期货报价。",
          )}
        </div>
      </Panel>
      <Panel
        title={t("Around the exchanges", "全球交易时段")}
        sub={t(
          "Regular sessions · local exchange time",
          "常规交易时段 · 交易所当地时间",
        )}
      >
        <div className="exchange-list">
          {exchanges.map((e: any) => (
            <div className="exchange" key={e.code}>
              <div className="exchange-mark">
                {e.code === "XNYS"
                  ? "US"
                  : e.code === "XLON"
                    ? "GB"
                    : e.code === "XAMS"
                      ? "NL"
                      : e.code === "XETR"
                        ? "DE"
                        : e.code === "XHKG"
                          ? "HK"
                          : e.code === "XTKS"
                            ? "JP"
                            : "CN"}
              </div>
              <div>
                <strong>{e.name}</strong>
                <span>
                  {e.city} <b>·</b> {e.local_time || "—"}
                </span>
                {full && (
                  <small>
                    {t("Next open", "下次开盘")}{" "}
                    {date(e.next_open, user.settings.language)}
                  </small>
                )}
              </div>
              <Tag tone={e.status === "open" ? "green" : ""}>
                <i className={`tiny-dot ${e.status === "open" ? "" : "off"}`} />
                {e.status === "open"
                  ? t("Open", "交易中")
                  : e.status === "closed"
                    ? t("Closed", "休市")
                    : t("Unknown", "未知")}
              </Tag>
            </div>
          ))}
        </div>
        <div className="panel-foot">
          {t(
            "Holiday, daylight-saving and lunch-break aware. Scheduled sessions do not reflect intraday halts.",
            "日历包含假期、夏令时和午间休市，不包含盘中临时停牌。",
          )}
        </div>
      </Panel>
    </>
  );
}

export function Overview({
  navigate,
  portfolioOnly = false,
}: {
  navigate: (p: string) => void;
  portfolioOnly?: boolean;
}) {
  const { t, user } = useApp(),
    r = useResource("/portfolio", user.settings.portfolio_interval * 1000),
    news = useResource("/news"),
    analyses = useResource("/ai/analyses");
  const action = useAction();
  const [selected, setSelected] = useState<any>(null);
  const [filter, setFilter] = useState("");
  const p = r.data?.snapshot?.data,
    currency = p?.currency || "EUR",
    positions = p?.positions || [],
    timeline = r.data?.timeline || [];
  const sync = () =>
    action.run(
      async () => {
        await post("/portfolio/sync");
        r.reload();
      },
      t("Portfolio synchronized", "持仓已同步"),
    );
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("YOUR INVESTMENT WORKSPACE", "你的投资研究工作台")}
          </div>
          <h1>
            {portfolioOnly
              ? t("Portfolio", "投资组合")
              : t("A clearer view of your investments.", "看清投资的每一面。")}
          </h1>
          <p>
            {t(
              "Your holdings, the wider market, and what matters next.",
              "连接持仓、市场和下一步值得关注的信息。",
            )}
          </p>
        </div>
        <Button secondary busy={action.busy} onClick={sync}>
          <RefreshCw size={16} />
          {t("Sync portfolio", "同步持仓")}
        </Button>
      </div>
      {r.error && <ResourceError error={r.error} retry={r.reload} />}
      {r.data?.status?.data?.error && (
        <div className="notice amber">
          {t(
            "The latest sync failed. Displaying the last successful snapshot.",
            "最近同步失败，正在显示上次成功同步的数据。",
          )}{" "}
          {date(r.data.snapshot?.updated_at, user.settings.language)}
        </div>
      )}
      <div className="metrics">
        {[
          [
            t("Portfolio value", "账户总价值"),
            p?.total_value,
            t("Investments + cash", "投资与现金"),
            <Wallet size={17} />,
          ],
          [
            t("Invested capital", "当前持仓成本"),
            p?.invested,
            t("Cost basis of open positions", "当前持仓的成本基础"),
            <CircleDollarSign size={17} />,
          ],
          [
            t("Unrealized return", "未实现收益"),
            p?.unrealized,
            t("Across open positions", "当前持仓浮动盈亏"),
            <ChartNoAxesCombined size={17} />,
          ],
          [
            t("Realized return", "已实现收益"),
            p?.realized,
            t("Reported by Trading 212", "Trading 212 报告值"),
            <ArrowUpRight size={17} />,
          ],
        ].map(([label, value, sub, icon], i) => (
          <div className={`metric ${i === 0 ? "primary-metric" : ""}`} key={i}>
            <div className="metric-label">
              {label as string}
              {icon}
            </div>
            <strong
              className={
                i > 1 && value != null
                  ? Number(value) >= 0
                    ? "positive"
                    : "negative"
                  : ""
              }
            >
              {money(value as number, currency, user.settings.language)}
            </strong>
            <div className="metric-note">
              {i > 1 && value != null && Number(value) >= 0 ? (
                <span className="tiny-dot" />
              ) : null}
              {sub as string}
            </div>
          </div>
        ))}
      </div>
      {!p && (
        <div className="connect-banner">
          <div className="banner-icon">
            <Cable size={23} />
          </div>
          <div>
            <h3>
              {t("Bring your portfolio into focus", "从连接你的投资账户开始")}
            </h3>
            <p>
              {t(
                "Connect Trading 212 to follow holdings, performance and the news around them.",
                "连接 Trading 212，跟踪持仓、收益及相关动态。",
              )}
            </p>
          </div>
          <Button onClick={() => navigate("settings")}>
            {t("Connect account", "连接账户")}
            <ArrowRight size={16} />
          </Button>
        </div>
      )}
      {p && (
        <div className="snapshot-meta">
          <Tag tone={p.environment === "demo" ? "amber" : "green"}>
            {p.environment === "demo"
              ? t("Demo account", "模拟账户")
              : "Trading 212"}
          </Tag>
          <span>
            {t("Updated", "更新于")} {date(p.as_of, user.settings.language)}
          </span>
          <span>
            {t("Cash / deposit", "现金 / Deposit")}{" "}
            {money(p.cash, currency, user.settings.language)}
          </span>
          {p.cash_in_pies > 0 && (
            <span>
              {t("Cash in pies", "Pie 内现金")}{" "}
              {money(p.cash_in_pies, currency, user.settings.language)}
            </span>
          )}
          {p.cash_reserved > 0 && (
            <span>
              {t("Reserved funds", "预留资金")}{" "}
              {money(p.cash_reserved, currency, user.settings.language)}
            </span>
          )}
        </div>
      )}
      <div className={portfolioOnly ? "portfolio-layout" : "dashboard-layout"}>
        <div className="main-column">
          <Panel
            title={t("Your holdings", "当前持仓")}
            sub={`${positions.length} ${t("assets in your portfolio", "项持仓")}${p?.pies?.length ? ` · ${p.pies.length} Pies` : ""}`}
            action={
              <input
                className="compact-search"
                placeholder={t("Find a holding…", "查找持仓…")}
                aria-label={t("Find a holding", "查找持仓")}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            }
          >
            {positions.length || p?.pies?.length ? (
              <HoldingsTable
                portfolio={p}
                filter={filter}
                onSelect={setSelected}
              />
            ) : (
              <Empty
                icon={<Wallet size={24} />}
                title={t("Your holdings will live here", "在这里查看你的持仓")}
                body={t(
                  "A single view of each position, its return and price history.",
                  "集中查看每项资产、收益及历史 K 线。",
                )}
                action={
                  <button
                    className="text-button"
                    onClick={() => navigate("settings")}
                  >
                    {t("Set up Trading 212", "配置 Trading 212")}
                    <ArrowRight size={15} />
                  </button>
                }
              />
            )}
          </Panel>
          {selected && (
            <Panel
              title={`${selected.name || selected.ticker} · ${t("Price history", "历史 K 线")}`}
              action={
                <button
                  className="text-button"
                  onClick={() => setSelected(null)}
                >
                  {t("Close", "关闭")}
                </button>
              }
            >
              <PriceChart
                ticker={selected.ticker}
                symbol={selected.chart_symbol}
              />
            </Panel>
          )}
          {timeline.length > 1 && (
            <Panel
              title={t("Account value over time", "账户价值变化")}
              sub={t(
                "Snapshots collected by Peat · includes deposits and withdrawals",
                "Peat 本地采集的快照 · 含入金与出金影响",
              )}
            >
              <div className="timeline">
                <Sparkline
                  height={100}
                  values={timeline.map((item: any) => item.total_value)}
                />
              </div>
              <div className="source-line">
                <span>
                  {date(timeline[0].created_at, user.settings.language)}
                </span>
                <span>
                  {date(timeline.at(-1).created_at, user.settings.language)}
                </span>
              </div>
            </Panel>
          )}
          {!portfolioOnly && (
            <Panel
              title={t("On your radar", "值得关注")}
              sub={t(
                "The latest news around your holdings and watchlist",
                "与你的持仓及关注列表相关的最新消息",
              )}
              action={
                <button
                  className="text-button"
                  onClick={() => navigate("news")}
                >
                  {t("All news", "全部新闻")}
                  <ArrowRight size={15} />
                </button>
              }
            >
              {news.data?.items?.length ? (
                <div className="news-preview">
                  {news.data.items.slice(0, 3).map((n: any) => (
                    <NewsArticle key={n.id} article={n} compact />
                  ))}
                </div>
              ) : (
                <Empty
                  title={t("Start with what you follow", "从你关注的公司开始")}
                  body={t(
                    "Add companies to your watchlist, then collect their latest news.",
                    "添加关注公司，即可获取相关新闻与行业动态。",
                  )}
                  action={
                    <button
                      className="text-button"
                      onClick={() => navigate("watchlist")}
                    >
                      {t("Build your watchlist", "添加关注")}
                      <Plus size={15} />
                    </button>
                  }
                />
              )}
            </Panel>
          )}
        </div>
        <aside className="side-column">
          {!portfolioOnly && (
            <section className="insight-card">
              <div className="insight-top">
                <span className="insight-icon">
                  <Sprout size={22} />
                </span>
                <Tag>
                  {t("PE AT INTELLIGENCE", "PEAT 智能研究").replace(
                    "PE AT",
                    "PEAT",
                  )}
                </Tag>
              </div>
              <h2>
                {t(
                  "A little context.\nA clearer decision.",
                  "多一分洞察，\n多一分清晰。",
                )}
              </h2>
              <p>
                {analyses.data?.length
                  ? t(
                      "Your latest research brief is ready. Revisit the evidence and the signals to watch.",
                      "最近的研究简报已就绪，查看相关证据与跟踪信号。",
                    )
                  : t(
                      "Turn your portfolio, market signals and news into a brief that fits your investment style.",
                      "结合持仓、市场信号与新闻，生成符合你投资风格的研究简报。",
                    )}
              </p>
              <Button onClick={() => navigate("intelligence")}>
                {t("Open intelligence", "打开智能研究")}
                <ArrowUpRight size={17} />
              </Button>
              <div className="insight-foot">
                {t(
                  "Your model. Your perspective.",
                  "选择你的模型，形成你的判断。",
                )}
              </div>
            </section>
          )}
          <MarketsPanel />
        </aside>
      </div>
    </>
  );
}

export function Watchlist() {
  const { t } = useApp(),
    r = useResource("/watchlist"),
    action = useAction();
  const [symbol, setSymbol] = useState(""),
    [name, setName] = useState(""),
    [sector, setSector] = useState(""),
    [selected, setSelected] = useState<any>(null);
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">
            {t("KEEP AN EYE ON WHAT MATTERS", "关注值得研究的公司")}
          </div>
          <h1>{t("Watchlist", "关注列表")}</h1>
          <p>
            {t(
              "Follow companies and the industries around them.",
              "跟踪公司及其所在行业的变化。",
            )}
          </p>
        </div>
      </div>
      <Panel title={t("Add a company", "添加公司")}>
        <form
          className="watch-form"
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(
              async () => {
                await post("/watchlist", { symbol, name, sector });
                setSymbol("");
                setName("");
                setSector("");
                r.reload();
              },
              t("Company added", "已添加公司"),
            );
          }}
        >
          <label>
            {t("Symbol", "股票代码")}
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="AAPL"
              required
              maxLength={30}
            />
          </label>
          <label>
            {t("Company", "公司名称")}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Apple"
              required
              maxLength={120}
            />
          </label>
          <label>
            {t("Industry", "所属行业")}
            <input
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              placeholder={t("Consumer electronics", "消费电子")}
              maxLength={100}
            />
          </label>
          <Button busy={action.busy}>
            <Plus size={17} />
            {t("Add company", "添加公司")}
          </Button>
        </form>
      </Panel>
      {r.error && <ResourceError error={r.error} retry={r.reload} />}
      <div className="watch-grid">
        {r.data?.map((w: any, i: number) => (
          <div className="watch-card" key={w.id}>
            <div className="watch-card-head">
              <span className={`asset-avatar color-${i % 5}`}>
                {w.symbol.slice(0, 2)}
              </span>
              <button
                className="icon-button"
                aria-label={t("Remove ", "移除 ") + w.name}
                onClick={() =>
                  action.run(async () => {
                    await del("/watchlist/" + w.id);
                    r.reload();
                  })
                }
              >
                <Trash2 size={15} />
              </button>
            </div>
            <h3>{w.name}</h3>
            <p>
              {w.symbol} <span>·</span>{" "}
              {w.sector || t("Industry not set", "未设置行业")}
            </p>
            <button className="text-button" onClick={() => setSelected(w)}>
              {t("Explore price history", "查看历史 K 线")}
              <ArrowUpRight size={15} />
            </button>
          </div>
        ))}
      </div>
      {!r.loading && !r.data?.length && (
        <Panel title={t("Your companies", "你关注的公司")}>
          <Empty
            title={t("Make it your watchlist", "建立你的关注列表")}
            body={t(
              "Add your first company above. News will follow your selections.",
              "在上方添加第一家公司，新闻会随你的关注同步。",
            )}
          />
        </Panel>
      )}
      {selected && (
        <Panel
          title={selected.name}
          action={
            <button className="text-button" onClick={() => setSelected(null)}>
              {t("Close", "关闭")}
            </button>
          }
        >
          <PriceChart ticker={selected.symbol} symbol={selected.symbol} />
        </Panel>
      )}
    </>
  );
}
