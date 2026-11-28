"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { ShortcutHelp } from "@/components/shortcut-help";
import { dialogOpen, shortcutKey } from "@/lib/shortcuts";

/**
 * Esc closes the invoice and goes back to the queue (an open dialog closes first, by itself);
 * ? lists the keys. a and r live in the decision panel, next to the forms they open.
 */
export function InvoiceShortcuts() {
  const t = useTranslations("Shortcuts");
  const router = useRouter();

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (shortcutKey(event) === "Escape" && !dialogOpen()) {
        event.preventDefault();
        router.push("/invoices");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <ShortcutHelp
      shortcuts={[
        { keys: "a", action: t("approve") },
        { keys: "r", action: t("reject") },
        { keys: "Esc", action: t("close") },
        { keys: "?", action: t("help") },
      ]}
    />
  );
}
