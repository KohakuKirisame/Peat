import { useState } from "react";
import { ChevronDown, ChevronUp, LoaderCircle, RefreshCw } from "lucide-react";
import { date, errorMessage, post, useApp } from "./api";
import { Button, External, Tag } from "./ui";

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
    await load();
  }
  async function load(refresh = false) {
    setBusy(true);
    setError("");
    try {
      setBody(
        await post(
          `/news/${article.id}/fulltext${refresh ? "?refresh=true" : ""}`,
        ),
      );
    } catch (error) {
      setError(errorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }
  const reasons: Record<string, string> = {
    article_subscription_required: t(
      "This article requires a subscription.",
      "此文章需要订阅。",
    ),
    article_access_restricted: t(
      "The publisher limits automated access.",
      "来源限制了自动读取。",
    ),
    article_dynamic_page: t(
      "The article is loaded by scripts; the readable version is unavailable.",
      "正文通过脚本加载，暂未取得可读版本。",
    ),
    article_not_found: t(
      "The publisher page has moved or was removed.",
      "原文页面已移动或移除。",
    ),
    article_rate_limited: t(
      "The publisher is limiting requests. Try again shortly.",
      "来源请求频率受限，请稍后重试。",
    ),
    article_timeout: t(
      "The publisher took too long to respond. You can retry.",
      "来源响应较慢，可以重试。",
    ),
    article_source_temporary: t(
      "The publisher is temporarily unavailable. You can retry.",
      "来源暂时不可用，可以重试。",
    ),
    article_link_unavailable: t(
      "Could not resolve the original article link. You can retry.",
      "原文链接解析失败，可以重试。",
    ),
  };
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
            <>
              <p role="alert">{error}</p>
              <Button secondary onClick={() => load(true)}>
                <RefreshCw size={14} />
                {t("Retry article", "重试获取")}
              </Button>
            </>
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
            <div className="article-retry">
              <p>
                {reasons[body?.error] ||
                  t(
                    "Article text is currently unavailable.",
                    "正文暂未获取。",
                  )}{" "}
                <External href={body?.source_url || article.url}>
                  {t("Open the original article", "打开原文")}
                </External>
              </p>
              <Button secondary onClick={() => load(true)}>
                <RefreshCw size={14} />
                {t("Retry article", "重试获取")}
              </Button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
