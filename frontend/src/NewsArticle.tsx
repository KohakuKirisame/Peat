import { useState } from "react";
import { ChevronDown, ChevronUp, LoaderCircle } from "lucide-react";
import { date, errorMessage, post, useApp } from "./api";
import { External, Tag } from "./ui";

export function NewsArticle({
  article,
  compact = false,
}: {
  article: any;
  compact?: boolean;
}) {
  const { t, user } = useApp();
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false);
  const [body, setBody] = useState<any>(null),
    [error, setError] = useState("");
  const detailsId = `news-fulltext-${article.id}`;
  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || body || busy) return;
    setBusy(true);
    setError("");
    try {
      setBody(await post(`/news/${article.id}/fulltext`));
    } catch (error) {
      setError(errorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className={compact ? "compact-article" : ""}>
      <div className="article-meta">
        {!compact && <Tag>{article.topic}</Tag>}
        <span>{article.source}</span>
        <span>·</span>
        <time>
          {date(
            article.published_at || article.fetched_at,
            user.settings.language,
          )}
        </time>
      </div>
      {compact ? (
        <h3>
          <External href={article.url}>{article.title}</External>
        </h3>
      ) : (
        <h2>
          <External href={article.url}>{article.title}</External>
        </h2>
      )}
      <p>{article.content}</p>
      <div className="article-controls">
        <button
          className="text-button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={detailsId}
        >
          {busy ? (
            <LoaderCircle size={15} className="spin" />
          ) : open ? (
            <ChevronUp size={15} />
          ) : (
            <ChevronDown size={15} />
          )}
          {open
            ? t("Collapse article", "收起正文")
            : t("Read full article", "展开全文")}
        </button>
        <span className="article-id">[news {article.id}]</span>
      </div>
      {open && (
        <div id={detailsId} className="article-expanded" aria-live="polite">
          {busy ? (
            <p className="muted">
              {t("Fetching article text…", "正在获取正文…")}
            </p>
          ) : error ? (
            <p role="alert">{error}</p>
          ) : body?.status === "ready" ? (
            <>
              <div className="article-fulltext">{body.content}</div>
              <div className="source-line">
                <External href={body.source_url}>
                  {t("Original article", "原文")}
                </External>
                <span>
                  {t("Saved", "保存于")}{" "}
                  {date(body.fetched_at, user.settings.language)}
                </span>
              </div>
              {body.truncated && (
                <p className="field-hint">
                  {t(
                    "Showing the first 60,000 characters. Open the original for the rest.",
                    "显示前 60,000 字，剩余内容可打开原文查看。",
                  )}
                </p>
              )}
            </>
          ) : (
            <p>
              {t("Article text is currently unavailable. ", "正文暂未获取，")}
              <External href={body?.source_url || article.url}>
                {t("Open the original article", "打开原文")}
              </External>
            </p>
          )}
        </div>
      )}
    </article>
  );
}
