import { Fragment, useState } from "react";
import { ChartPie, ChevronDown, ChevronRight } from "lucide-react";
import { date, money, num, useApp } from "./api";

export type Holding = {
  ticker: string;
  name: string;
  quantity: number | null;
  price: number | null;
  currency: string;
  account_currency?: string;
  value: number | null;
  pnl: number | null;
  chart_symbol?: string;
  partial_position?: boolean;
};

type Pie = {
  id: number;
  name: string;
  value: number | null;
  pnl: number | null;
  cash: number | null;
  account_currency?: string;
  as_of?: string;
  positions: Holding[];
};

export function HoldingsTable({
  portfolio,
  filter,
  onSelect,
}: {
  portfolio: {
    positions: Holding[];
    ungrouped_positions?: Holding[];
    pies?: Pie[];
    currency: string;
    market_value: number | null;
    pie_status?: { state: string; error: string | null };
  };
  filter: string;
  onSelect: (holding: Holding) => void;
}) {
  const { t, user } = useApp();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const query = filter.trim().toLocaleLowerCase();
  const matches = (holding: Holding) =>
    `${holding.name} ${holding.ticker}`.toLocaleLowerCase().includes(query);
  const pies = (portfolio.pies || []).filter(
    (pie) =>
      pie.name.toLocaleLowerCase().includes(query) ||
      pie.positions.some(matches),
  );
  const individual = (
    portfolio.ungrouped_positions || portfolio.positions
  ).filter(matches);
  const currency = portfolio.currency;
  const format = (value: number | null, unit = currency) =>
    money(value, unit, user.settings.language);
  const weight = (value: number | null) =>
    portfolio.market_value && value !== null
      ? (value / portfolio.market_value) * 100
      : null;

  function valueCells(holding: Holding | Pie) {
    const share = weight(holding.value);
    return (
      <>
        <td>{format(holding.value, holding.account_currency || currency)}</td>
        <td
          className={
            holding.pnl === null
              ? ""
              : holding.pnl >= 0
                ? "positive"
                : "negative"
          }
        >
          {format(holding.pnl, holding.account_currency || currency)}
          {"partial_position" in holding && holding.partial_position && (
            <small
              title={t(
                "The outside-Pie lot's cost basis is not supplied by the API.",
                "API 未提供 Pie 外这部分持仓的独立成本基础。",
              )}
            >
              {t("Cost basis unavailable", "独立成本未提供")}
            </small>
          )}
        </td>
        <td>
          {share === null ? "—" : `${num(share, 1)}%`}
          <div className="weight-bar">
            <i
              style={{ width: `${Math.min(100, Math.max(0, share || 0))}%` }}
            />
          </div>
        </td>
      </>
    );
  }

  function holdingRow(holding: Holding, index: number, nested = false) {
    return (
      <tr
        key={holding.ticker}
        className={`clickable ${nested ? "pie-child" : ""}`}
        onClick={() => onSelect(holding)}
      >
        <td>
          <button
            className="holding-name"
            onClick={(event) => {
              event.stopPropagation();
              onSelect(holding);
            }}
          >
            <span className={`asset-avatar color-${index % 5}`}>
              {holding.ticker.split("_")[0].slice(0, 2)}
            </span>
            <span>
              <strong>{holding.name || holding.ticker}</strong>
              <small>
                {holding.ticker.split("_")[0]} · {num(holding.quantity, 6)}{" "}
                {t("shares", "股")}
                {holding.partial_position &&
                  ` · ${t("outside pies", "Pie 外")}`}
              </small>
            </span>
          </button>
        </td>
        <td>
          {format(holding.price, holding.currency)}
          <small>{holding.currency}</small>
        </td>
        {valueCells(holding)}
      </tr>
    );
  }

  const status = portfolio.pie_status;
  return (
    <>
      {status?.error && (
        <div className="holdings-notice" role="status">
          {status.state === "stale"
            ? t(
                "Pie details could not be refreshed. Showing the last matched Pie snapshot.",
                "Pie 详情刷新失败，显示上次与持仓数量匹配的分组。",
              )
            : status.error === "pies_permission_required"
              ? t(
                  "Enable pies:read on your Trading 212 API key to display Pie groups. Showing individual holdings.",
                  "请为 Trading 212 API Key 开启 pies:read 权限以显示 Pie 分组；当前显示逐项持仓。",
                )
              : status.error === "pies_out_of_sync"
                ? t(
                    "Pie allocations and positions are updating. Showing individual holdings until they match.",
                    "Pie 分配与持仓数量正在更新，匹配前先显示逐项持仓。",
                  )
                : t(
                    "Pie details are unavailable. Showing individual holdings.",
                    "暂时无法读取 Pie 详情，当前显示逐项持仓。",
                  )}
        </div>
      )}
      <div className="table-scroll">
        <table className="holdings-table">
          <thead>
            <tr>
              <th>{t("Asset", "资产")}</th>
              <th>{t("Price", "现价")}</th>
              <th>{t("Value", "市值")}</th>
              <th>{t("Return", "收益")}</th>
              <th>{t("Weight", "占比")}</th>
            </tr>
          </thead>
          {pies.map((pie) => {
            const matchesName = pie.name.toLocaleLowerCase().includes(query);
            const children = matchesName
              ? pie.positions
              : pie.positions.filter(matches);
            const key = `${pie.id}:${query}`;
            const open = expanded[key] ?? Boolean(query && !matchesName);
            const detailsId = `pie-holdings-${pie.id}`;
            return (
              <Fragment key={pie.id}>
                <tbody className="pie-header">
                  <tr>
                    <td>
                      <button
                        className="pie-toggle"
                        aria-expanded={open}
                        aria-controls={detailsId}
                        aria-label={`${open ? t("Collapse pie", "收起 Pie") : t("Expand pie", "展开 Pie")} ${pie.name}`}
                        onClick={() =>
                          setExpanded((current) => ({
                            ...current,
                            [key]: !open,
                          }))
                        }
                      >
                        {open ? (
                          <ChevronDown size={16} />
                        ) : (
                          <ChevronRight size={16} />
                        )}
                        <span className="asset-avatar pie-avatar">
                          <ChartPie size={20} />
                        </span>
                        <span className="pie-label">
                          <strong>{pie.name}</strong>
                          <small>
                            Pie · {pie.positions.length}{" "}
                            {t("holdings", "项持仓")}
                          </small>
                          <small className="pie-updated">
                            {date(pie.as_of, user.settings.language)}
                          </small>
                        </span>
                      </button>
                    </td>
                    <td className="pie-cash">
                      <span>{t("Basket", "组合")}</span>
                    </td>
                    {valueCells(pie)}
                  </tr>
                </tbody>
                <tbody id={detailsId} hidden={!open} className="pie-details">
                  <tr className="pie-detail-meta">
                    <td colSpan={5}>
                      {t("Pie snapshot", "Pie 数据时间")} ·{" "}
                      {date(pie.as_of, user.settings.language)} ·{" "}
                      {t("Trading 212 reported values", "Trading 212 报告值")}
                    </td>
                  </tr>
                  {children.map((holding, index) =>
                    holdingRow(holding, index, true),
                  )}
                  {!children.length && (
                    <tr>
                      <td colSpan={5} className="pie-empty">
                        {t(
                          "This pie has no invested holdings.",
                          "此 Pie 暂无已投资持仓。",
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </Fragment>
            );
          })}
          {individual.length > 0 && (
            <tbody className="individual-holdings">
              {Boolean(portfolio.pies?.length) && (
                <tr className="holdings-section">
                  <td colSpan={5}>
                    {t(
                      "Individual holdings · outside pies",
                      "独立持仓 · Pie 外",
                    )}
                  </td>
                </tr>
              )}
              {individual.map((holding, index) => holdingRow(holding, index))}
            </tbody>
          )}
          {!pies.length && !individual.length && (
            <tbody>
              <tr>
                <td colSpan={5} className="pie-empty">
                  {t("No matching holdings.", "没有匹配的持仓。")}
                </td>
              </tr>
            </tbody>
          )}
        </table>
      </div>
    </>
  );
}
