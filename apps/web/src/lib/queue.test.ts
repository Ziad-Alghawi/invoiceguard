import { describe, expect, it } from "vitest";

import {
  ageInDays,
  formatAmount,
  formatDate,
  isQueueSort,
  nextDueSort,
} from "@/lib/invoices";

describe("queue columns", () => {
  it("formats the gross amount in its currency and the UI language", () => {
    const nbsp = String.fromCharCode(0xa0);
    expect(formatAmount("5137.23", "EUR", "de")).toBe(`5.137,23${nbsp}€`);
    expect(formatAmount("5137.23", "EUR", "en")).toBe("€5,137.23");
    expect(formatAmount("12", null, "de")).toBe("12,00");
    expect(formatAmount("12", "XX1", "en")).toBe("12.00 XX1");
    expect(formatAmount("n/a", "EUR", "de")).toBe("n/a");
  });

  it("formats the due date without shifting the day", () => {
    expect(formatDate("2026-11-19", "de")).toBe("19.11.2026");
    expect(formatDate("2026-11-19", "en")).toBe("Nov 19, 2026");
    expect(formatDate("garbage", "de")).toBe("garbage");
  });

  it("counts the age in whole days in Berlin time", () => {
    const now = new Date("2026-11-27T10:00:00Z");
    expect(ageInDays("2026-11-27T08:00:00Z", now)).toBe(0);
    // 23:30 UTC on the 26th is already the 27th in Berlin.
    expect(ageInDays("2026-11-26T23:30:00Z", now)).toBe(0);
    expect(ageInDays("2026-11-26T22:30:00Z", now)).toBe(1);
    expect(ageInDays("2026-11-17T12:00:00Z", now)).toBe(10);
  });

  it("sorts by due date, soonest first, then latest first", () => {
    expect(nextDueSort("received")).toBe("due_date");
    expect(nextDueSort("due_date")).toBe("-due_date");
    expect(nextDueSort("-due_date")).toBe("due_date");
    expect(isQueueSort("-due_date")).toBe(true);
    expect(isQueueSort("amount")).toBe(false);
  });
});
