import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { SecurityEventsTable } from "@/components/security-events-table";
import { apiFetch, ApiError, errorMessage } from "@/lib/api";
import type { SecurityEvent } from "@/lib/security";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("Metadata"))("security") };
}

const LIMIT = 100;

async function Events() {
  const t = await getTranslations("Security");
  const response = await apiFetch(`/security-events?limit=${LIMIT}`);
  if (response.status === 403) {
    // The API logged the attempt; reviewers see why there is nothing here.
    return <p className="text-sm text-muted-foreground">{t("forbidden")}</p>;
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  const events = (await response.json()) as SecurityEvent[];
  const total = Number(response.headers.get("X-Total-Count") ?? events.length);
  return (
    <>
      <p className="text-sm text-muted-foreground">
        {total > events.length
          ? t("introLatest", { shown: events.length, total })
          : t("introAll")}
      </p>
      <SecurityEventsTable events={events} />
    </>
  );
}

export default function SecurityPage() {
  const t = useTranslations("Security");
  const common = useTranslations("Common");
  return (
    <main className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground">{common("loading")}</p>
        }
      >
        <Events />
      </Suspense>
    </main>
  );
}
