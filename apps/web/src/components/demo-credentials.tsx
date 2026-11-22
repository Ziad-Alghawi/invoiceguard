import { useTranslations } from "next-intl";

import type { DemoLogin } from "@/lib/demo";

/** The public demo's shared logins, shown on purpose: the data is made up and reset daily. */
export function DemoCredentials({ logins }: { logins: DemoLogin[] }) {
  const t = useTranslations("DemoCredentials");
  const roles = useTranslations("Codes.role");
  return (
    <section
      aria-label={t("label")}
      className="rounded-md border bg-muted/50 p-3 text-sm"
    >
      <p className="font-medium">{t("title")}</p>
      {logins.map((login) => (
        <dl
          key={login.role}
          className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5"
        >
          <dt className="text-muted-foreground">{t("role")}</dt>
          <dd>{roles(login.role)}</dd>
          <dt className="text-muted-foreground">{t("email")}</dt>
          <dd className="font-mono break-all">{login.email}</dd>
          <dt className="text-muted-foreground">{t("password")}</dt>
          <dd className="font-mono break-all">{login.password}</dd>
        </dl>
      ))}
      <p className="mt-2 text-xs text-muted-foreground">{t("note")}</p>
    </section>
  );
}
