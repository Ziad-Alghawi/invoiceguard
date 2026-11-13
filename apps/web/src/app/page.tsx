import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { HealthStatus } from "@/components/health-status";
import { checkApiHealth, getApiUrl } from "@/lib/health";

async function ApiHealth() {
  await connection();
  const status = await checkApiHealth(getApiUrl());
  return <HealthStatus status={status} />;
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-4 p-6">
      <h1 className="font-heading text-2xl font-semibold">InvoiceGuard</h1>
      <Suspense
        fallback={
          <p role="status" className="text-sm text-muted-foreground">
            Checking API…
          </p>
        }
      >
        <ApiHealth />
      </Suspense>
      <Link href="/invoices" className="text-sm underline underline-offset-4">
        Open the review queue
      </Link>
    </main>
  );
}
