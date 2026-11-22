import type { Metadata } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { connection } from "next/server";
import { Suspense } from "react";

import { invoiceStatus } from "@/app/actions";
import { UploadForm } from "@/components/upload-form";
import { getDemoLogins } from "@/lib/demo";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("Metadata"))("upload") };
}

async function DemoNote() {
  // Read at request time: one image serves local runs and the demo.
  await connection();
  if (getDemoLogins().length === 0) {
    return null;
  }
  const t = await getTranslations("Upload");
  return <p className="text-sm text-muted-foreground">{t("demoNote")}</p>;
}

/** Upload one invoice; every logged-in user may (reviewers and approvers). */
export default function UploadPage() {
  const t = useTranslations("Upload");
  const common = useTranslations("Common");
  return (
    <main className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-heading text-2xl font-semibold">{t("title")}</h1>
        <Link href="/invoices" className="text-sm underline underline-offset-4">
          {common("backToQueue")}
        </Link>
      </div>
      <p className="text-sm">{t("intro")}</p>
      <Suspense fallback={null}>
        <DemoNote />
      </Suspense>
      <UploadForm getStatus={invoiceStatus} />
    </main>
  );
}
