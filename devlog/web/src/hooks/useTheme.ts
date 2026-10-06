/** 全站明暗主题。
 *
 * 颜色本身全部写在 styles.css 的变量里，这里只负责一件事：把
 * data-theme 挂到 <html> 上，并记到 localStorage，刷新后不回到默认值。
 * index.html 里还有一段同逻辑的内联脚本，负责在 React 挂载前就把主题
 * 定好，否则会先闪一帧黑底再变白。
 */

import { useCallback, useEffect, useState } from "react";

export type ThemeName = "dark" | "light";

export const THEME_STORAGE_KEY = "devlog-theme";

const THEME_COLOR: Record<ThemeName, string> = {
  dark: "#0d1117",
  light: "#ffffff",
};

/** 读取用户选过的主题；没选过或存了脏值都退回深色。 */
export function readStoredTheme(): ThemeName {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "light"
      ? "light"
      : "dark";
  } catch {
    // 隐私模式下 localStorage 会抛异常，不能因此白屏。
    return "dark";
  }
}

/** 把主题写到 DOM 上，顺带更新浏览器地址栏的配色。 */
export function applyTheme(theme: ThemeName): void {
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", THEME_COLOR[theme]);
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemeName>(readStoredTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((previous) => {
      const next: ThemeName = previous === "dark" ? "light" : "dark";
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // 存不了就算了：这次会话内照样能切，只是刷新后回到默认。
      }
      return next;
    });
  }, []);

  return { theme, toggleTheme };
}
