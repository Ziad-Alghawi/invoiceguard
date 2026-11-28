"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";
import {
  THEME_COOKIE,
  THEME_COOKIE_MAX_AGE,
  type Theme,
  themeFromCookie,
  THEMES,
} from "@/lib/theme";

const ICONS = { system: Monitor, light: Sun, dark: Moon } as const;
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Saves the choice and applies it at once with the head script's function (lib/theme.ts). */
function choose(theme: Theme) {
  document.cookie =
    theme === "system"
      ? `${THEME_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`
      : `${THEME_COOKIE}=${theme}; Path=/; Max-Age=${THEME_COOKIE_MAX_AGE}; SameSite=Lax`;
  (window as Window & { __applyTheme?: () => void }).__applyTheme?.();
  listeners.forEach((listener) => listener());
}

/** System | light | dark, in the header. The server does not know the choice: none is marked there. */
export function ThemeSwitch() {
  const t = useTranslations("Theme");
  const current = useSyncExternalStore<Theme | null>(
    subscribe,
    () => themeFromCookie(document.cookie),
    () => null,
  );
  return (
    <div
      role="group"
      aria-label={t("label")}
      className="flex items-center gap-0.5"
    >
      {THEMES.map((theme) => {
        const Icon = ICONS[theme];
        return (
          <button
            key={theme}
            type="button"
            aria-label={t(theme)}
            title={t(theme)}
            aria-pressed={current === theme}
            onClick={() => choose(theme)}
            className={cn(
              "rounded p-1",
              current === theme
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon aria-hidden="true" className="size-4" />
          </button>
        );
      })}
    </div>
  );
}
