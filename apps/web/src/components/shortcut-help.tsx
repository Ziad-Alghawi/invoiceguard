"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { shortcutKey } from "@/lib/shortcuts";

export type Shortcut = { keys: string; action: string };

/** "?" opens a list of the page's shortcuts; Esc or the button closes it. */
export function ShortcutHelp({ shortcuts }: { shortcuts: Shortcut[] }) {
  const t = useTranslations("Shortcuts");
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (shortcutKey(event) === "?") {
        event.preventDefault();
        dialog.current?.showModal();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <dialog
      ref={dialog}
      aria-labelledby="shortcut-help-title"
      className="m-auto rounded-md border bg-background p-4 text-foreground shadow-lg backdrop:bg-black/40"
    >
      <h2 id="shortcut-help-title" className="mb-3 text-base font-semibold">
        {t("title")}
      </h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {shortcuts.map((shortcut) => (
          <div key={shortcut.keys} className="contents">
            <dt>
              <kbd className="rounded border px-1.5 font-mono">
                {shortcut.keys}
              </kbd>
            </dt>
            <dd>{shortcut.action}</dd>
          </div>
        ))}
      </dl>
      <form method="dialog" className="mt-4 flex justify-end">
        <button type="submit" className="rounded-md border px-3 py-1 text-sm">
          {t("close")}
        </button>
      </form>
    </dialog>
  );
}
