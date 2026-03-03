import { useTheme as useNextTheme } from "next-themes";

export type Theme = "light" | "dark" | "system";

export function useTheme() {
  const { theme, setTheme, resolvedTheme } = useNextTheme();
  return {
    theme: theme as Theme | undefined,
    resolvedTheme: resolvedTheme as "light" | "dark" | undefined,
    setTheme: (t: Theme) => setTheme(t),
    isDark: resolvedTheme === "dark",
  };
}
