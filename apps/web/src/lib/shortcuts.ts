/** Keyboard shortcuts (P1): which key press is a shortcut and which is typing. */

const TYPING = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** True while the user types: in a text field, a list box or editable content. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return TYPING.has(target.tagName) || target.isContentEditable;
}

/**
 * The key of a shortcut, or null: never while typing, never with Ctrl, Alt or Meta (those
 * belong to the browser), never inside an open dialog (it has its own keys).
 */
export function shortcutKey(event: KeyboardEvent): string | null {
  if (event.ctrlKey || event.altKey || event.metaKey || event.isComposing) {
    return null;
  }
  if (isTypingTarget(event.target)) {
    return null;
  }
  if (
    event.target instanceof Element &&
    event.target.closest("dialog[open]") !== null
  ) {
    return null;
  }
  return event.key;
}

/** True when a modal dialog is open; Esc then closes it and does nothing else. */
export function dialogOpen(): boolean {
  return document.querySelector("dialog[open]") !== null;
}
