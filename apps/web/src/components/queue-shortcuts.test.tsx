import { cleanup, fireEvent } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { QueueShortcuts } from "@/components/queue-shortcuts";
import { renderWithIntl } from "@/test/intl";

afterEach(cleanup);

beforeAll(() => {
  HTMLElement.prototype.scrollIntoView = () => undefined;
});

describe("QueueShortcuts", () => {
  it("j and k move the focus through the queue's invoices", () => {
    renderWithIntl(
      <>
        <a href="#invoice-1" data-queue-link>
          one
        </a>
        <a href="#invoice-2" data-queue-link>
          two
        </a>
        <input aria-label="search" />
        <QueueShortcuts />
      </>,
    );
    const [one, two] = document.querySelectorAll("a");
    fireEvent.keyDown(document.body, { key: "j" });
    expect(document.activeElement).toBe(one);
    fireEvent.keyDown(one, { key: "j" });
    expect(document.activeElement).toBe(two);
    fireEvent.keyDown(two, { key: "j" });
    expect(document.activeElement).toBe(two);
    fireEvent.keyDown(two, { key: "k" });
    expect(document.activeElement).toBe(one);

    const input = document.querySelector("input")!;
    input.focus();
    fireEvent.keyDown(input, { key: "j" });
    expect(document.activeElement).toBe(input);
  });
});
