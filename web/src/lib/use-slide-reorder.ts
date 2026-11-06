"use client";

import { useCallback, useLayoutEffect, useRef } from "react";

/**
 * Animates items of a list to their new place when the order changes: each item slides from where it
 * was to where it is now. Returns a ref callback per item id.
 */
export function useSlideReorder(ids: string[]) {
  const nodes = useRef(new Map<string, HTMLElement>());
  const tops = useRef(new Map<string, number>());
  const order = ids.join(" ");

  useLayoutEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    nodes.current.forEach((node, id) => {
      // Relative to the list, so scrolling it doesn't count as moving.
      const top = node.offsetTop;
      const before = tops.current.get(id);
      if (before !== undefined && before !== top && !reduced) {
        node.animate(
          [{ transform: `translateY(${before - top}px)` }, { transform: "translateY(0)" }],
          { duration: 350, easing: "cubic-bezier(0.2, 0, 0, 1)" },
        );
      }
      tops.current.set(id, top);
    });
  }, [order]);

  return useCallback(
    (id: string) => (node: HTMLElement | null) => {
      if (node) nodes.current.set(id, node);
      else nodes.current.delete(id);
    },
    [],
  );
}
