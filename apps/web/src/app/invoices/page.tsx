import Link from "next/link";
import { useTranslations } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { exportDatev } from "@/app/actions";
import { ExportButton } from "@/components/export-button";
import { QueueShortcuts } from "@/components/queue-shortcuts";
import { StatusBadge } from "@/components/status-badge";
import { StatusReason } from "@/components/status-reason";
import { apiFetch, ApiError, errorMessage } from "@/lib/api";
import {
  ageInDays,
  formatAmount,
  formatDate,
  formatDateTime,
  invoiceReason,
  isQueueFilter,
  isQueueSort,
  nextDueSort,
  QUEUE_FILTERS,
  type QueueFilter,
  type QueueItem,
  type QueueSort,
} from "@/lib/invoices";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function queueHref(
  filter: QueueFilter,
  page = 1,
  sort: QueueSort = "received",
): string {
  const query = new URLSearchParams({ filter });
  if (sort !== "received") {
    query.set("sort", sort);
  }
  if (page > 1) {
    query.set("page", String(page));
  }
  return `/invoices?${query}`;
}

const ARIA_SORT = {
  due_date: "ascending",
  "-due_date": "descending",
  received: undefined,
} as const;

async function Queue({ searchParams }: { searchParams: SearchParams }) {
  const t = await getTranslations("Queue");
  const locale = await getLocale();
  const params = await searchParams;
  const filter = isQueueFilter(params.filter) ? params.filter : "review";
  const sort = isQueueSort(params.sort) ? params.sort : "received";
  const page = Math.max(
    1,
    Number.parseInt(String(params.page ?? "1"), 10) || 1,
  );

  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    sort,
  });
  for (const status of QUEUE_FILTERS[filter].statuses) {
    query.append("status", status);
  }
  const response = await apiFetch(`/invoices?${query}`);
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  const invoices = (await response.json()) as QueueItem[];
  const now = new Date();
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
            href={queueHref(key, 1, sort)}
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
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th scope="col" className="py-2 font-medium">
                  {t("file")}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t("supplier")}
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  {t("gross")}
                </th>
                <th
                  scope="col"
                  aria-sort={ARIA_SORT[sort]}
                  className="py-2 font-medium"
                >
                  <Link
                    href={queueHref(filter, 1, nextDueSort(sort))}
                    className="underline underline-offset-4"
                  >
                    {t(
                      sort === "due_date"
                        ? "dueSortedAsc"
                        : sort === "-due_date"
                          ? "dueSortedDesc"
                          : "due",
                    )}
                  </Link>
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  {t("age")}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t("status")}
                </th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id} className="border-t align-top">
                  <td className="py-2 pr-3">
                    <Link
                      href={`/invoices/${invoice.id}`}
                      data-queue-link
                      className="rounded-sm font-medium underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                    >
                      {invoice.original_filename}
                    </Link>
                    {invoice.status_reason && (
                      <p className="text-xs text-muted-foreground">
                        <StatusReason reason={invoiceReason(invoice)} />
                      </p>
                    )}
                  </td>
                  <td className="py-2 pr-3">{invoice.supplier ?? "–"}</td>
                  <td className="py-2 pr-3 text-right whitespace-nowrap tabular-nums">
                    {invoice.gross_total === null
                      ? "–"
                      : formatAmount(
                          invoice.gross_total,
                          invoice.currency,
                          locale,
                        )}
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    {invoice.due_date === null
                      ? "–"
                      : formatDate(invoice.due_date, locale)}
                  </td>
                  <td
                    className="py-2 pr-3 text-right whitespace-nowrap tabular-nums"
                    title={formatDateTime(invoice.created_at, locale)}
                  >
                    {t("ageDays", { days: ageInDays(invoice.created_at, now) })}
                  </td>
                  <td className="py-2">
                    <StatusBadge status={invoice.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav
        aria-label={t("pagesLabel")}
        className="flex items-center gap-4 text-sm text-muted-foreground"
      >
        {page > 1 && (
          <Link href={queueHref(filter, page - 1, sort)} className="underline">
            {t("previous")}
          </Link>
        )}
        <span>{t("pageInfo", { page, pages, total })}</span>
        {page < pages && (
          <Link href={queueHref(filter, page + 1, sort)} className="underline">
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
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold">{t("title")}</h1>
          <p className="text-xs text-muted-foreground">{t("shortcutsHint")}</p>
        </div>
        <ExportButton exportDatev={exportDatev} />
      </div>
      <QueueShortcuts />
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
