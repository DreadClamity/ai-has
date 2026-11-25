"use client";

import { useEffect, useState } from "react";

export const themeKey = "aihas_theme";

export default function ThemeToggle() {
  const [theme, setTheme] = useState("dark");

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);

  function changeTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem(themeKey, next);
    } catch {
      // The current page still supports both themes if storage is unavailable.
    }
  }

  const nextLabel = theme === "dark" ? "Light mode" : "Dark mode";
  return <button type="button" className="btn theme-toggle" onClick={changeTheme}>{nextLabel}</button>;
}
