import { Fragment, type ReactNode } from "react";
import en from "../messages/en.json";

/**
 * Proofit's replacement for next-intl (removed — English only now, no more
 * `km` locale). Same call shape as `useTranslations`/`getTranslations` so
 * every existing `t("key")` / `t.rich("key", {...})` call site needed only
 * an import swap, not a rewrite.
 */

type MessageNode = string | { [key: string]: MessageNode };

const messages: MessageNode = en;

function resolve(path: string): MessageNode | undefined {
  return path.split(".").reduce<MessageNode | undefined>((node, key) => {
    if (typeof node === "object" && node !== null && key in node) {
      return node[key];
    }
    return undefined;
  }, messages);
}

function interpolate(
  template: string,
  vars?: Record<string, string | number>,
): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

/** One level of `<tag>chunk</tag>` substitution — the only rich-text shape
 * Proofit's copy actually uses (landing page's `hero.title`). */
function renderRich(
  template: string,
  tags: Record<string, (chunks: ReactNode) => ReactNode>,
): ReactNode {
  const tagPattern = /<(\w+)>(.*?)<\/\1>/g;
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = tagPattern.exec(template)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(template.slice(lastIndex, match.index));
    }
    const [full, tagName, inner] = match;
    const render = tags[tagName];
    nodes.push(
      <Fragment key={key++}>{render ? render(inner) : inner}</Fragment>,
    );
    lastIndex = match.index + full.length;
  }
  if (lastIndex < template.length) {
    nodes.push(template.slice(lastIndex));
  }
  return nodes;
}

function requireString(fullKey: string): string {
  const value = resolve(fullKey);
  if (typeof value !== "string") {
    throw new Error(`Missing copy for "${fullKey}"`);
  }
  return value;
}

export interface Translator {
  (key: string, vars?: Record<string, string | number>): string;
  rich: (
    key: string,
    tags: Record<string, (chunks: ReactNode) => ReactNode>,
  ) => ReactNode;
}

function makeTranslator(namespace?: string): Translator {
  const withNamespace = (key: string) =>
    namespace ? `${namespace}.${key}` : key;

  const t = ((key: string, vars?: Record<string, string | number>) =>
    interpolate(requireString(withNamespace(key)), vars)) as Translator;

  t.rich = (key, tags) => renderRich(requireString(withNamespace(key)), tags);

  return t;
}

/** Drop-in replacement for next-intl's `useTranslations` — not an actual
 * React hook (no internal state), so it is safe to call from server
 * components too. */
export function useTranslations(namespace?: string): Translator {
  return makeTranslator(namespace);
}

/** Drop-in replacement for next-intl/server's `getTranslations`. Stays
 * async to match every existing `await getTranslations(...)` call site. */
export async function getTranslations(
  namespaceOrOptions?: string | { namespace?: string },
): Promise<Translator> {
  const namespace =
    typeof namespaceOrOptions === "string"
      ? namespaceOrOptions
      : namespaceOrOptions?.namespace;
  return makeTranslator(namespace);
}
