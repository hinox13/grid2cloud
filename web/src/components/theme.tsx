import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getStored, setStored } from "./hooks";

type Theme = "dark" | "light";
const Ctx = createContext<{ theme: Theme; set: (t: Theme) => void }>({ theme: "dark", set: () => {} });

function initial(): Theme {
  const q = new URLSearchParams(location.hash.split("?")[1] ?? "").get("theme");
  if (q === "dark" || q === "light") return q;
  const s = getStored("c2g-theme");
  if (s === "dark" || s === "light") return s;
  return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#050f16" : "#ffffff");
  }, [theme]);
  const set = (t: Theme) => {
    setTheme(t);
    setStored("c2g-theme", t);
  };
  return <Ctx.Provider value={{ theme, set }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx).theme;

export function ThemeToggle() {
  const { theme, set } = useContext(Ctx);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="btn-text theme-toggle" onClick={() => set(next)} aria-label={`Switch to ${next} theme`}>
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
