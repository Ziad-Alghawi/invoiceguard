import type messages from "../../messages/en.json";
import type { Locale } from "@/i18n/config";

// Typed keys: a `t("…")` call with a key missing from en.json fails the type check.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof messages;
  }
}
