"use client";

import { useTranslations } from "next-intl";
import { useActionState, useEffect } from "react";

import { exportFileHref, type ExportState, exportSummary } from "@/lib/exports";

const INITIAL: ExportState = { error: null, export: null };

function download(href: string) {
  window.location.assign(href);
}

/**
 * Exports the approved invoices to a DATEV booking file and starts its download. The file stays
 * available through "Download again"; an invoice is never put into a second file.
 */
export function ExportButton({
  exportDatev,
  startDownload = download,
}: {
  exportDatev: () => Promise<ExportState>;
  startDownload?: (href: string) => void;
}) {
  const t = useTranslations("Export");
  const [state, action, pending] = useActionState(exportDatev, INITIAL);
  const exportId = state.export?.id;

  useEffect(() => {
    if (exportId) {
      startDownload(exportFileHref(exportId));
    }
  }, [exportId, startDownload]);

  return (
    <form action={action} className="flex flex-col items-end gap-1 text-sm">
      <button
        type="submit"
        disabled={pending}
        className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 font-medium text-primary-foreground disabled:opacity-50"
      >
        {pending ? t("exporting") : t("button")}
      </button>
      {state.export && (
        <div role="status" className="text-right">
          {exportSummary(state.export).map((line) => (
            <p key={line.key}>{t(line.key, { count: line.count })}</p>
          ))}
          <a
            href={exportFileHref(state.export.id)}
            className="underline underline-offset-4"
          >
            {t("downloadAgain")}
          </a>
        </div>
      )}
      {state.error && (
        <p role="alert" className="text-destructive">
          {state.error}
        </p>
      )}
    </form>
  );
}
