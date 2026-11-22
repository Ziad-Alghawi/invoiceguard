import { render, type RenderOptions } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import { type Locale, TIME_ZONE } from "@/i18n/config";

export const MESSAGES = { de, en } as const;

/** Renders a component with the messages of one language, English unless a test says otherwise. */
export function renderWithIntl(
  ui: ReactElement,
  { locale = "en", ...options }: RenderOptions & { locale?: Locale } = {},
) {
  return render(ui, {
    wrapper: ({ children }) => (
      <NextIntlClientProvider
        locale={locale}
        messages={MESSAGES[locale]}
        timeZone={TIME_ZONE}
      >
        {children}
      </NextIntlClientProvider>
    ),
    ...options,
  });
}
