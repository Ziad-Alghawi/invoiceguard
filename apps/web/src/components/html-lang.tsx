"use client";

import { useEffect } from "react";

/**
 * Keeps <html lang> in step after the language switch, which re-renders the page without a
 * full load (the inline script in the root layout covers full loads).
 */
export function HtmlLang({ locale }: { locale: string }) {
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  return null;
}
