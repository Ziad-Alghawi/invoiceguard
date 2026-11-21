import type { Metadata } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("Metadata"))("notFound") };
}

/** Unknown paths and invoices (notFound() in the detail page), in the UI language. */
export default function NotFound() {
  const t = useTranslations("NotFound");
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-4 p-6">
      <h1 className="font-heading text-2xl font-semibold">{t("title")}</h1>
      <p className="text-sm">{t("text")}</p>
      <Link href="/invoices" className="text-sm underline underline-offset-4">
        {t("home")}
      </Link>
    </main>
  );
}
