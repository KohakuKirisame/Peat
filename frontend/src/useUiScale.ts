import { useLayoutEffect, useMemo, useState } from "react";

const originalMedia = new WeakMap<CSSMediaRule, string>();
const normalize = (value: number) =>
  Number.isFinite(value)
    ? Math.min(200, Math.max(80, Math.round(value / 5) * 5))
    : 100;

function applyScale(percent: number) {
  const scale = percent / 100;
  document.documentElement.style.zoom = String(scale);
  document.documentElement.style.setProperty("--ui-scale", String(scale));
  // CSS zoom changes layout width, but viewport media queries still use the unscaled width.
  // Keep the existing responsive layouts at the same effective width for every zoom level.
  const update = (rules: CSSRuleList) => {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSMediaRule) {
        if (!originalMedia.has(rule))
          originalMedia.set(rule, rule.media.mediaText);
        rule.media.mediaText = originalMedia
          .get(rule)!
          .replace(
            /\((min|max)-width:\s*([\d.]+)px\)/g,
            (_, bound, width) => `(${bound}-width: ${Number(width) * scale}px)`,
          );
      }
      if ("cssRules" in rule) update((rule as CSSGroupingRule).cssRules);
    }
  };
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      update(sheet.cssRules);
    } catch {
      /* External stylesheets may disallow CSSOM access. */
    }
  }
}

export function useUiScale(userId?: number) {
  const key = userId ? `peat-ui-scale:${userId}` : null;
  const saved = useMemo(() => {
    try {
      const value = key ? localStorage.getItem(key) : null;
      return value === null ? 100 : normalize(Number(value));
    } catch {
      return 100;
    }
  }, [key]);
  const [selection, setSelection] = useState<{
    key: string | null;
    value: number;
  } | null>(null);
  const scale = selection?.key === key ? selection.value : saved;
  useLayoutEffect(() => {
    applyScale(scale);
    return () => applyScale(100);
  }, [scale]);
  const setScale = (value: number) => {
    const next = normalize(value);
    setSelection({ key, value: next });
    try {
      if (key) localStorage.setItem(key, String(next));
    } catch {
      /* Remains usable without persistent storage. */
    }
  };
  return { scale, setScale };
}
