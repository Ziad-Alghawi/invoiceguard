import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { invoiceStatus } from "@/app/actions";
import { UploadForm } from "@/components/upload-form";
import { getDemoLogins } from "@/lib/demo";

export const metadata = { title: "Upload · InvoiceGuard" };

async function DemoNote() {
  // Read at request time: one image serves local runs and the demo.
  await connection();
  if (getDemoLogins().length === 0) {
    return null;
  }
  return (
    <p className="text-sm text-muted-foreground">
      Public demo: PDFs without embedded XML are refused, because no model runs
      on visitors&apos; files. Uploads are limited per hour, and every invoice
      uploaded here is deleted by the nightly reset.
    </p>
  );
}

/** Upload one invoice; every logged-in user may (reviewers and approvers). */
export default function UploadPage() {
  return (
    <main className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-heading text-2xl font-semibold">
          Upload an invoice
        </h1>
        <Link href="/invoices" className="text-sm underline underline-offset-4">
          ← Queue
        </Link>
      </div>
      <p className="text-sm">
        An XRechnung XML (UBL or CII) or a ZUGFeRD / Factur-X PDF with embedded
        XML, up to 10 MB. The invoice is checked right after the upload and then
        waits in the queue for review.
      </p>
      <Suspense fallback={null}>
        <DemoNote />
      </Suspense>
      <UploadForm getStatus={invoiceStatus} />
    </main>
  );
}
