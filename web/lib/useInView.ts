"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Fires once, the first time the ref'd element scrolls into view — the
 * source design's own `IntersectionObserver` + 5s fallback-timeout pattern
 * (its `DCLogic.componentDidMount`), reimplemented as a hook so Landing's
 * evidence scene and the Results coverage ring can both use it. Never
 * un-fires: once true, stays true (matches the source, which disconnects
 * its observer on first intersection).
 */
export function useInView<T extends Element>(threshold = 0.2) {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || inView) return;

    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setInView(true);
            observer.disconnect();
          }
        }
      },
      { threshold },
    );
    observer.observe(el);
    const fallback = window.setTimeout(() => setInView(true), 5000);

    return () => {
      observer.disconnect();
      window.clearTimeout(fallback);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `inView` is a latch, not a dep
  }, [threshold]);

  return { ref, inView };
}

/**
 * Eases 0 → `target` over `duration`ms once `active` becomes true, matching
 * the source design's count-up (quartic ease-out, `requestAnimationFrame`,
 * respects `prefers-reduced-motion`, cancels its own frame on unmount).
 */
export function useCountUp(
  target: number,
  active: boolean,
  { duration = 1700, delay = 0 }: { duration?: number; delay?: number } = {},
): number {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!active) return;
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setValue(target);
      return;
    }

    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.min(1, Math.max(0, (now - start - delay) / duration));
      const eased = 1 - Math.pow(1 - elapsed, 4);
      setValue(Math.round(target * eased));
      if (elapsed < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(raf);
  }, [active, target, duration, delay]);

  return value;
}
