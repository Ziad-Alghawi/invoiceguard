import Link from "next/link";
import { Suspense } from "react";

import { logout } from "@/app/actions";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/invoices";

async function CurrentUser() {
  const user = await apiGet<User>("/auth/me");
  return (
    <form action={logout} className="flex items-center gap-3 text-sm">
      <span className="text-muted-foreground">{user.display_name}</span>
      <button type="submit" className="underline underline-offset-4">
        Log out
      </button>
    </form>
  );
}

export default function InvoicesLayout({ children }: LayoutProps<"/invoices">) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-6">
      <header className="flex items-center justify-between gap-4 border-b pb-3">
        <Link href="/invoices" className="font-heading text-lg font-semibold">
          InvoiceGuard · Review
        </Link>
        <Suspense fallback={null}>
          <CurrentUser />
        </Suspense>
      </header>
      {children}
    </div>
  );
}
