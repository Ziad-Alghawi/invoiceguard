import { Suspense } from "react";

import { SecurityEventsTable } from "@/components/security-events-table";
import { apiFetch, ApiError, errorMessage } from "@/lib/api";
import type { SecurityEvent } from "@/lib/security";

export const metadata = { title: "Security events · InvoiceGuard" };

const LIMIT = 100;

async function Events() {
  const response = await apiFetch(`/security-events?limit=${LIMIT}`);
  if (response.status === 403) {
    // The API logged the attempt; reviewers see why there is nothing here.
    return (
      <p className="text-sm text-muted-foreground">
        Only users with the approver role can read the security events.
      </p>
    );
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  const events = (await response.json()) as SecurityEvent[];
  const total = Number(response.headers.get("X-Total-Count") ?? events.length);
  return (
    <>
      <p className="text-sm text-muted-foreground">
        Failed logins, lockouts, refused role checks, self-approval attempts and
        prompt injections found in invoices. Newest first
        {total > events.length
          ? `, the latest ${events.length} of ${total}`
          : ""}
        . Read-only: the log cannot be changed.
      </p>
      <SecurityEventsTable events={events} />
    </>
  );
}

export default function SecurityPage() {
  return (
    <main className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Security events</h1>
      <Suspense
        fallback={<p className="text-sm text-muted-foreground">Loading…</p>}
      >
        <Events />
      </Suspense>
    </main>
  );
}
