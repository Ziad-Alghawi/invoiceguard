import Link from "next/link";
import { Suspense } from "react";

import { StatusBadge } from "@/components/status-badge";
import { apiFetch, ApiError, errorMessage } from "@/lib/api";
import {
  formatDateTime,
  type Invoice,
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
      <nav aria-label="Queue filter" className="flex flex-wrap gap-2">
        {Object.entries(QUEUE_FILTERS).map(([key, { label }]) => (
          <Link
            key={key}
            href={queueHref(key as QueueFilter)}
            aria-current={key === filter ? "page" : undefined}
            className={cn(
              "rounded-md border px-3 py-1 text-sm",
              key === filter && "bg-primary text-primary-foreground",
            )}
          >
            {label}
          </Link>
        ))}
      </nav>
      {invoices.length === 0 ? (
        <p className="text-sm text-muted-foreground">No invoices here.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="py-2 font-medium">
                File
              </th>
              <th scope="col" className="py-2 font-medium">
                Status
              </th>
              <th scope="col" className="py-2 font-medium">
                Received
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
                      {invoice.status_reason}
                    </p>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <StatusBadge status={invoice.status} />
                </td>
                <td className="py-2 whitespace-nowrap">
                  {formatDateTime(invoice.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <nav
        aria-label="Pages"
        className="flex items-center gap-4 text-sm text-muted-foreground"
      >
        {page > 1 && (
          <Link href={queueHref(filter, page - 1)} className="underline">
            Previous
          </Link>
        )}
        <span>
          Page {page} of {pages} · {total} invoices
        </span>
        {page < pages && (
          <Link href={queueHref(filter, page + 1)} className="underline">
            Next
          </Link>
        )}
      </nav>
    </>
  );
}

export default function QueuePage({ searchParams }: PageProps<"/invoices">) {
  return (
    <main className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Invoice queue</h1>
      <Suspense
        fallback={<p className="text-sm text-muted-foreground">Loading…</p>}
      >
        <Queue searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
