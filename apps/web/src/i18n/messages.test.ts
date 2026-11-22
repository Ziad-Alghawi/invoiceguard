import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import { LOCALES } from "@/i18n/config";

type Tree = { [key: string]: string | Tree };

const MESSAGES: Record<(typeof LOCALES)[number], Tree> = { de, en };

/** Every message as "Namespace.key" → text. */
function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const result = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") {
      result.set(path, value);
    } else {
      for (const [child, text] of flatten(value, path)) {
        result.set(child, text);
      }
    }
  }
  return result;
}

/** The argument names a message uses: "{name}", "{count, plural, …}". Tags: "<time>". */
function argumentsOf(text: string): { names: string[]; tags: string[] } {
  const names = [...text.matchAll(/\{\s*(\w+)\s*[,}]/g)].map((m) => m[1]);
  const tags = [...text.matchAll(/<(\w+)>/g)].map((m) => m[1]);
  return { names, tags };
}

const english = flatten(en);

describe("messages", () => {
  it.each(LOCALES)("%s has the same keys as English", (locale) => {
    const keys = [...flatten(MESSAGES[locale]).keys()].sort();
    expect(keys).toEqual([...english.keys()].sort());
  });

  it.each(LOCALES)("%s has no empty message", (locale) => {
    const empty = [...flatten(MESSAGES[locale])]
      .filter(([, text]) => text.trim() === "")
      .map(([key]) => key);
    expect(empty).toEqual([]);
  });

  // Formats every message with the arguments its English text names: a syntax error, or an
  // argument the English text does not have, fails here instead of on a page.
  it.each(LOCALES)("%s formats every message", (locale) => {
    const errors: string[] = [];
    const t = createTranslator({
      locale,
      messages: MESSAGES[locale],
      timeZone: "Europe/Berlin",
      onError: (error) => errors.push(error.message),
    });
    for (const [key, text] of english) {
      const { names, tags } = argumentsOf(text);
      const values: Record<string, unknown> = {};
      for (const name of names) {
        values[name] = 1;
      }
      for (const tag of tags) {
        values[tag] = (chunks: unknown) => chunks;
      }
      // The keys are only known at run time here; the type check covers them in the code.
      (t.rich as (key: string, values: object) => unknown)(key, values);
    }
    expect(errors).toEqual([]);
  });
});
