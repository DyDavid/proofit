/**
 * Proofit — class-name helper.
 *
 * Deliberately dependency-free: no `clsx`, no `tailwind-merge`. It joins truthy
 * class values and drops exact duplicates, preserving first-appearance order.
 *
 * NOTE ON SCOPE: `cn` does NOT resolve conflicting Tailwind utilities. Passing
 * both `p-2` and `p-4` yields `"p-2 p-4"` and the winner is decided by CSS source
 * order, not by argument order. Primitives in `components/ui/` therefore keep
 * their variant maps free of properties a caller is expected to override, and
 * a caller who needs to override a padding/colour should pass the variant prop
 * rather than fighting it with `className`.
 */

/** A plain object whose truthy keys become class names. */
export type ClassDictionary = Record<string, boolean | null | undefined>;

/** Anything `cn` accepts: strings, numbers, falsy values, nested arrays, dictionaries. */
export type ClassValue =
  | string
  | number
  | false
  | null
  | undefined
  | ClassDictionary
  | ClassValue[];

/**
 * Merge class values into a single deduplicated, space-separated string.
 *
 * @example
 * cn("px-3", isActive && "bg-brand-600", { "sr-only": hidden }, ["a", "a"])
 * // -> "px-3 bg-brand-600 a"   (when isActive is true and hidden is false)
 */
export function cn(...inputs: ClassValue[]): string {
  const seen = new Set<string>();
  const out: string[] = [];

  const push = (raw: string): void => {
    for (const token of raw.split(/\s+/)) {
      if (token === "" || seen.has(token)) continue;
      seen.add(token);
      out.push(token);
    }
  };

  const walk = (value: ClassValue): void => {
    if (value === null || value === undefined || value === false) return;
    if (typeof value === "string") {
      push(value);
      return;
    }
    if (typeof value === "number") {
      push(String(value));
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    for (const key of Object.keys(value)) {
      if (value[key]) push(key);
    }
  };

  for (const input of inputs) walk(input);
  return out.join(" ");
}

/**
 * Clamp a number into an inclusive range. Used by `CoverageStat` to keep a
 * 0–100 value sane even if the engine emits an out-of-range score.
 */
export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}
