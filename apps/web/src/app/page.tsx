import { connection } from "next/server";
import { Suspense } from "react";

import { HealthStatus } from "@/components/health-status";
import { checkApiHealth } from "@/lib/health";

async function ApiHealth() {
  await connection();
  const status = await checkApiHealth(process.env.NEXT_PUBLIC_API_URL);
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
    </main>
  );
}
