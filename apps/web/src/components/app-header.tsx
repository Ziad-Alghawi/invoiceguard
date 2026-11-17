import Link from "next/link";
import { Suspense } from "react";

import { logout } from "@/app/actions";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/invoices";

async function CurrentUser() {
  const user = await apiGet<User>("/auth/me");
  return (
    <div className="flex items-center gap-4 text-sm">
      {user.role === "approver" && (
        <Link href="/security" className="underline underline-offset-4">
          Security events
        </Link>
      )}
      <form action={logout} className="flex items-center gap-3">
        <span className="text-muted-foreground">
          {user.display_name} · {user.role}
        </span>
        <button type="submit" className="underline underline-offset-4">
          Log out
        </button>
      </form>
    </div>
  );
}

/** The header of the logged-in pages: home link, the user with their role, log out. */
export function AppHeader() {
  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b pb-3">
      <Link href="/invoices" className="font-heading text-lg font-semibold">
        InvoiceGuard · Review
      </Link>
      <Suspense fallback={null}>
        <CurrentUser />
      </Suspense>
    </header>
  );
}
