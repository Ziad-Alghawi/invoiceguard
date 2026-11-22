import { useLocale, useTranslations } from "next-intl";

import { LOCALES } from "@/i18n/config";
import { cn } from "@/lib/utils";

const SHORT = { de: "shortDe", en: "shortEn" } as const;

/**
 * DE | EN. A plain form with a server action, so it works without JavaScript; the choice is
 * kept in a cookie and the page is rendered again in the new language.
 */
export function LocaleSwitch({
  setLocale,
}: {
  setLocale: (formData: FormData) => Promise<void>;
}) {
  const t = useTranslations("LocaleSwitch");
  const current = useLocale();
  return (
    <form
      action={setLocale}
      aria-label={t("label")}
      className="flex items-center gap-1 text-sm"
    >
      {LOCALES.map((locale) => (
        <button
          key={locale}
          type="submit"
          name="locale"
          value={locale}
          lang={locale}
          aria-label={t(locale)}
          aria-pressed={locale === current}
          className={cn(
            "rounded px-1.5 py-0.5",
            locale === current
              ? "bg-primary text-primary-foreground"
              : "underline underline-offset-4",
          )}
        >
          {t(SHORT[locale])}
        </button>
      ))}
    </form>
  );
}
