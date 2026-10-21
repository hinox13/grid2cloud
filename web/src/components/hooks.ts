import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** Element size via ResizeObserver (0×0 until measured). */
export function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, { w: number; h: number }] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setSize((s) => (Math.abs(s.w - width) < 0.5 && Math.abs(s.h - height) < 0.5 ? s : { w: width, h: height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

const RM = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [rm, setRm] = useState(() => typeof matchMedia !== "undefined" && matchMedia(RM).matches);
  useEffect(() => {
    const q = matchMedia(RM);
    const on = () => setRm(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return rm;
}

/** Hash routing: "#/explore/events?e=..." -> { path: "/explore/events", params }. Survives refresh on GitHub Pages. */
export function useHashRoute(): { path: string; params: URLSearchParams; go: (to: string) => void } {
  const read = () => {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, q = ""] = h.split("?");
    return { path: path || "/", params: new URLSearchParams(q) };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((to: string) => {
    location.hash = to;
  }, []);
  return { ...route, go };
}

export function setStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: preference lasts for this visit only */
  }
}

export function getStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
