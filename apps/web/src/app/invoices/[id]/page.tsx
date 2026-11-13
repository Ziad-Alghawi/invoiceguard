import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { approve, reject } from "@/app/actions";
import { AuditHistory } from "@/components/audit-history";
import { CheckList } from "@/components/check-list";
import { DecisionPanel } from "@/components/decision-panel";
import { FieldsTable } from "@/components/fields-table";
import { StatusBadge } from "@/components/status-badge";
import { apiGet, ApiError } from "@/lib/api";
import {
  type AuditEvent,
  formatDateTime,
  type InvoiceDetail,
  isInvoiceId,
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

async function load(id: string): Promise<[InvoiceDetail, AuditEvent[]]> {
  try {
    return await Promise.all([
      apiGet<InvoiceDetail>(`/invoices/${id}`),
      apiGet<AuditEvent[]>(`/invoices/${id}/audit`),
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
  const [invoice, history] = await load(id);
  const failedChecks = invoice.checks
    .filter((check) => check.status === "failed")
    .map((check) => check.type);
  const lowConfidence = invoice.fields.filter((field) => field.low_confidence);

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
          <p className="text-sm text-muted-foreground">
            {invoice.source_type.toUpperCase()} · received{" "}
            {formatDateTime(invoice.created_at)} ·{" "}
            <a
              href={`/invoices/${invoice.id}/file`}
              className="underline underline-offset-4"
            >
              Download original
            </a>
            {invoice.llm_calls > 0 &&
              ` · ${invoice.llm_calls} LLM call(s), $${invoice.llm_cost_usd}`}
          </p>
        </div>
        <Section title="Checks">
          <CheckList checks={invoice.checks} />
        </Section>
        <Section title="Extracted fields">
          {lowConfidence.length > 0 && (
            <p className="text-sm text-amber-800">
              {lowConfidence.length} field(s) with low confidence are
              highlighted: compare them with the original.
            </p>
          )}
          <FieldsTable fields={invoice.fields} />
        </Section>
      </div>
      <aside className="flex flex-col gap-6">
        <Section title="Decision">
          <DecisionPanel
            status={invoice.status}
            failedChecks={failedChecks}
            approve={approve.bind(null, invoice.id)}
            reject={reject.bind(null, invoice.id)}
          />
        </Section>
        <Section title="History">
          <AuditHistory events={history} />
        </Section>
      </aside>
    </div>
  );
}

export default function InvoicePage({ params }: PageProps<"/invoices/[id]">) {
  return (
    <main className="flex flex-col gap-4">
      <Link href="/invoices" className="text-sm underline underline-offset-4">
        ← Queue
      </Link>
      <Suspense
        fallback={<p className="text-sm text-muted-foreground">Loading…</p>}
      >
        <Detail params={params} />
      </Suspense>
    </main>
  );
}
