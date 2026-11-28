import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { logout, setLocale } from "@/app/actions";
import { LocaleSwitch } from "@/components/locale-switch";
import { ThemeSwitch } from "@/components/theme-switch";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/invoices";

async function CurrentUser() {
  const user = await apiGet<User>("/auth/me");
  const t = await getTranslations("Header");
  const roles = await getTranslations("Codes.role");
  return (
    <div className="flex items-center gap-4 text-sm">
      <Link href="/upload" className="underline underline-offset-4">
        {t("upload")}
      </Link>
      {user.role === "approver" && (
        <Link href="/security" className="underline underline-offset-4">
          {t("security")}
        </Link>
      )}
      <form action={logout} className="flex items-center gap-3">
        <span className="text-muted-foreground">
          {t("user", { name: user.display_name, role: roles(user.role) })}
        </span>
        <button type="submit" className="underline underline-offset-4">
          {t("logout")}
        </button>
      </form>
    </div>
  );
}

/** The header of the logged-in pages: home link, the user with their role, language, theme, log out. */
export function AppHeader() {
  const t = useTranslations("Header");
  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b pb-3">
      <Link href="/invoices" className="font-heading text-lg font-semibold">
        {t("home")}
      </Link>
      <div className="flex flex-wrap items-center gap-4">
        <Suspense fallback={null}>
          <CurrentUser />
        </Suspense>
        <LocaleSwitch setLocale={setLocale} />
        <ThemeSwitch />
      </div>
    </header>
  );
}
