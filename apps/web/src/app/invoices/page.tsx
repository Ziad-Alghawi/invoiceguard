import Link from "next/link";
import { useTranslations } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { exportDatev } from "@/app/actions";
import { ExportButton } from "@/components/export-button";
import { StatusBadge } from "@/components/status-badge";
import { StatusReason } from "@/components/status-reason";
import { apiFetch, ApiError, errorMessage } from "@/lib/api";
import {
  formatDateTime,
  type Invoice,
  invoiceReason,
  isQueueFilter,
  QUEUE_FILTERS,
  type QueueFilter,
} from "@/lib/invoices";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function queueHref(filter: QueueFilter, page = 1): string {
  return page > 1
    ? `/invoices?filter=${filter}&page=${page}`
    : `/invoices?filter=${filter}`;
}

async function Queue({ searchParams }: { searchParams: SearchParams }) {
  const t = await getTranslations("Queue");
  const locale = await getLocale();
  const params = await searchParams;
  const filter = isQueueFilter(params.filter) ? params.filter : "review";
  const page = Math.max(
    1,
    Number.parseInt(String(params.page ?? "1"), 10) || 1,
  );

  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
  });
  for (const status of QUEUE_FILTERS[filter].statuses) {
    query.append("status", status);
  }
  const response = await apiFetch(`/invoices?${query}`);
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  const invoices = (await response.json()) as Invoice[];
  const total = Number(
    response.headers.get("X-Total-Count") ?? invoices.length,
  );
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <nav aria-label={t("filterLabel")} className="flex flex-wrap gap-2">
        {(Object.keys(QUEUE_FILTERS) as QueueFilter[]).map((key) => (
          <Link
            key={key}
            href={queueHref(key)}
            aria-current={key === filter ? "page" : undefined}
            className={cn(
              "rounded-md border px-3 py-1 text-sm",
              key === filter && "bg-primary text-primary-foreground",
            )}
          >
            {t(`filters.${key}`)}
          </Link>
        ))}
      </nav>
      {invoices.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="py-2 font-medium">
                {t("file")}
              </th>
              <th scope="col" className="py-2 font-medium">
                {t("status")}
              </th>
              <th scope="col" className="py-2 font-medium">
                {t("received")}
              </th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((invoice) => (
              <tr key={invoice.id} className="border-t align-top">
                <td className="py-2 pr-3">
                  <Link
                    href={`/invoices/${invoice.id}`}
                    className="font-medium underline-offset-4 hover:underline"
                  >
                    {invoice.original_filename}
                  </Link>
                  {invoice.status_reason && (
                    <p className="text-xs text-muted-foreground">
                      <StatusReason reason={invoiceReason(invoice)} />
                    </p>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <StatusBadge status={invoice.status} />
                </td>
                <td className="py-2 whitespace-nowrap">
                  {formatDateTime(invoice.created_at, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <nav
        aria-label={t("pagesLabel")}
        className="flex items-center gap-4 text-sm text-muted-foreground"
      >
        {page > 1 && (
          <Link href={queueHref(filter, page - 1)} className="underline">
            {t("previous")}
          </Link>
        )}
        <span>{t("pageInfo", { page, pages, total })}</span>
        {page < pages && (
          <Link href={queueHref(filter, page + 1)} className="underline">
            {t("next")}
          </Link>
        )}
      </nav>
    </>
  );
}

export default function QueuePage({ searchParams }: PageProps<"/invoices">) {
  const t = useTranslations("Queue");
  const common = useTranslations("Common");
  return (
    <main className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <ExportButton exportDatev={exportDatev} />
      </div>
      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground">{common("loading")}</p>
        }
      >
        <Queue searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
