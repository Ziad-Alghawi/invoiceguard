import Link from "next/link";
import { notFound } from "next/navigation";
import { useTranslations } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import {
  approve,
  confirmOverride,
  declineOverride,
  reopen,
  investigate,
  reject,
  requestOverride,
} from "@/app/actions";
import { AuditHistory } from "@/components/audit-history";
import { CheckList } from "@/components/check-list";
import { DecisionPanel } from "@/components/decision-panel";
import { FieldsTable } from "@/components/fields-table";
import { InvestigationPanel } from "@/components/investigation-panel";
import { StatusBadge } from "@/components/status-badge";
import { apiGet, ApiError } from "@/lib/api";
import type { Bookings } from "@/lib/bookings";
import type { Investigation } from "@/lib/investigations";
import {
  type AuditEvent,
  formatDateTime,
  type InvoiceDetail,
  isInvoiceId,
  overrideBlocker,
  overrideRequester,
  type User,
} from "@/lib/invoices";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

async function load(
  id: string,
): Promise<[InvoiceDetail, AuditEvent[], User, Investigation, Bookings]> {
  try {
    return await Promise.all([
      apiGet<InvoiceDetail>(`/invoices/${id}`),
      apiGet<AuditEvent[]>(`/invoices/${id}/audit`),
      apiGet<User>("/auth/me"),
      apiGet<Investigation>(`/invoices/${id}/investigation`),
      apiGet<Bookings>(`/invoices/${id}/bookings`),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}

async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isInvoiceId(id)) {
    notFound();
  }
  const [invoice, history, user, investigation, bookings] = await load(id);
  const t = await getTranslations("Invoice");
  const locale = await getLocale();
  const requestedBy = overrideRequester(history);
  const failedChecks = invoice.checks
    .filter((check) => check.status === "failed")
    .map((check) => check.type);
  const lowConfidence = invoice.fields.filter((field) => field.low_confidence);
  const showInvestigation =
    investigation.run !== null ||
    invoice.status === "blocked" ||
    invoice.status === "override_requested";

  return (
    <div className="grid gap-8 md:grid-cols-[1fr_18rem]">
      <div className="flex min-w-0 flex-col gap-6">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold break-all">
              {invoice.original_filename}
            </h1>
            <StatusBadge status={invoice.status} />
          </div>
          {invoice.status_reason && (
            <p className="text-sm">{invoice.status_reason}</p>
          )}
          <p className="flex flex-wrap gap-x-1 text-sm text-muted-foreground">
            <span>
              {t("received", {
                source: invoice.source_type.toUpperCase(),
                date: formatDateTime(invoice.created_at, locale),
              })}
            </span>
            <span aria-hidden="true">·</span>
            <a
              href={`/invoices/${invoice.id}/file`}
              className="underline underline-offset-4"
            >
              {t("download")}
            </a>
            {invoice.llm_calls > 0 && (
              <>
                <span aria-hidden="true">·</span>
                <span>
                  {t("llmCalls", {
                    count: invoice.llm_calls,
                    cost: invoice.llm_cost_usd,
                  })}
                </span>
              </>
            )}
          </p>
        </div>
        <Section title={t("checks")}>
          <CheckList checks={invoice.checks} />
        </Section>
        {showInvestigation && (
          <Section title={t("investigation")}>
            <InvestigationPanel
              investigation={investigation}
              investigate={investigate.bind(null, invoice.id)}
            />
          </Section>
        )}
        <Section title={t("fields")}>
          {lowConfidence.length > 0 && (
            <p className="text-sm text-amber-800">
              {t("lowConfidence", { count: lowConfidence.length })}
            </p>
          )}
          <FieldsTable fields={invoice.fields} />
        </Section>
      </div>
      <aside className="flex flex-col gap-6">
        <Section title={t("decision")}>
          <DecisionPanel
            status={invoice.status}
            failedChecks={failedChecks}
            override={{
              requestedBy,
              blocker: overrideBlocker(user, requestedBy),
            }}
            bookings={bookings}
            actions={{
              approve: approve.bind(null, invoice.id),
              reject: reject.bind(null, invoice.id),
              requestOverride: requestOverride.bind(null, invoice.id),
              confirmOverride: confirmOverride.bind(null, invoice.id),
              declineOverride: declineOverride.bind(null, invoice.id),
              reopen: reopen.bind(null, invoice.id),
            }}
          />
        </Section>
        <Section title={t("history")}>
          <AuditHistory events={history} />
        </Section>
      </aside>
    </div>
  );
}

export default function InvoicePage({ params }: PageProps<"/invoices/[id]">) {
  const common = useTranslations("Common");
  return (
    <main className="flex flex-col gap-4">
      <Link href="/invoices" className="text-sm underline underline-offset-4">
        {common("backToQueue")}
      </Link>
      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground">{common("loading")}</p>
        }
      >
        <Detail params={params} />
      </Suspense>
    </main>
  );
}
