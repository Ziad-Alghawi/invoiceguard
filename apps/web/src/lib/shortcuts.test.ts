import { afterEach, describe, expect, it } from "vitest";

import { isTypingTarget, shortcutKey } from "@/lib/shortcuts";

afterEach(() => {
  document.body.innerHTML = "";
});

function keydown(key: string, target: Element, init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, ...init });
  Object.defineProperty(event, "target", { value: target });
  return event;
}

describe("shortcutKey", () => {
  it("passes a plain key on the page", () => {
    expect(shortcutKey(keydown("j", document.body))).toBe("j");
    expect(shortcutKey(keydown("?", document.body, { shiftKey: true }))).toBe(
      "?",
    );
  });

  it("ignores keys with Ctrl, Alt or Meta", () => {
    for (const modifier of ["ctrlKey", "altKey", "metaKey"]) {
      expect(
        shortcutKey(keydown("a", document.body, { [modifier]: true })),
      ).toBeNull();
    }
  });

  it("ignores typing in fields and keys inside an open dialog", () => {
    document.body.innerHTML =
      '<input id="i"><textarea id="t"></textarea><select id="s"></select><dialog open><button id="b"></button></dialog>';
    for (const id of ["i", "t", "s", "b"]) {
      expect(
        shortcutKey(keydown("a", document.getElementById(id)!)),
      ).toBeNull();
    }
    expect(isTypingTarget(document.getElementById("t"))).toBe(true);
    expect(isTypingTarget(null)).toBe(false);
  });
});
