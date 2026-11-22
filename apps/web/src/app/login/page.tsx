import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { connection } from "next/server";
import { Suspense } from "react";

import { login, setLocale } from "@/app/actions";
import { DemoCredentials } from "@/components/demo-credentials";
import { LocaleSwitch } from "@/components/locale-switch";
import { LoginForm } from "@/components/login-form";
import { getDemoLogins } from "@/lib/demo";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("Metadata"))("login") };
}

async function Demo() {
  // Read at request time, not at build time: one image serves local runs and the demo.
  await connection();
  const logins = getDemoLogins();
  return logins.length > 0 && <DemoCredentials logins={logins} />;
}

export default function LoginPage() {
  const t = useTranslations("Login");
  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-4 p-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-heading text-2xl font-semibold">InvoiceGuard</h1>
        <LocaleSwitch setLocale={setLocale} />
      </div>
      <p className="text-sm text-muted-foreground">{t("intro")}</p>
      <Suspense fallback={null}>
        <Demo />
      </Suspense>
      <LoginForm login={login} />
    </main>
  );
}
