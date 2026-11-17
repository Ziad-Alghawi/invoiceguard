import { connection } from "next/server";
import { Suspense } from "react";

import { login } from "@/app/actions";
import { DemoCredentials } from "@/components/demo-credentials";
import { LoginForm } from "@/components/login-form";
import { getDemoLogins } from "@/lib/demo";

export const metadata = { title: "Log in · InvoiceGuard" };

async function Demo() {
  // Read at request time, not at build time: one image serves local runs and the demo.
  await connection();
  const logins = getDemoLogins();
  return logins.length > 0 && <DemoCredentials logins={logins} />;
}

export default function LoginPage() {
  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-4 p-6">
      <h1 className="font-heading text-2xl font-semibold">InvoiceGuard</h1>
      <p className="text-sm text-muted-foreground">
        Log in with a seeded reviewer or approver account. There is no sign-up.
      </p>
      <Suspense fallback={null}>
        <Demo />
      </Suspense>
      <LoginForm login={login} />
    </main>
  );
}
