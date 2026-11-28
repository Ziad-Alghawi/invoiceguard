"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { ShortcutHelp } from "@/components/shortcut-help";
import { shortcutKey } from "@/lib/shortcuts";

/** The queue's invoice links, in table order. */
function links(): HTMLAnchorElement[] {
  return [
    ...document.querySelectorAll<HTMLAnchorElement>("a[data-queue-link]"),
  ];
}

/**
 * j and k move through the queue's invoices, Enter opens the focused one (a link opens on Enter
 * by itself), ? lists the keys.
 */
export function QueueShortcuts() {
  const t = useTranslations("Shortcuts");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const key = shortcutKey(event);
      if (key !== "j" && key !== "k") {
        return;
      }
      const all = links();
      if (all.length === 0) {
        return;
      }
      event.preventDefault();
      const current = all.indexOf(document.activeElement as HTMLAnchorElement);
      const next =
        current === -1
          ? key === "j"
            ? 0
            : all.length - 1
          : Math.min(
              Math.max(current + (key === "j" ? 1 : -1), 0),
              all.length - 1,
            );
      all[next].focus();
      all[next].scrollIntoView({ block: "nearest" });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <ShortcutHelp
      shortcuts={[
        { keys: "j", action: t("next") },
        { keys: "k", action: t("previous") },
        { keys: "Enter", action: t("open") },
        { keys: "?", action: t("help") },
      ]}
    />
  );
}
