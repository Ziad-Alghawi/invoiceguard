import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatusReason } from "@/components/status-reason";
import { renderWithIntl } from "@/test/intl";

afterEach(cleanup);

describe("StatusReason", () => {
  it("shows failed checks in German with the check names", () => {
    renderWithIntl(
      <StatusReason
        reason={{
          text: "Failed checks: po_match, iban.",
          code: "failed_checks",
          checks: ["po_match", "iban"],
        }}
      />,
      { locale: "de" },
    );
    expect(
      screen.getByText("Fehlgeschlagene Prüfungen: Bestellabgleich, IBAN."),
    ).toBeTruthy();
  });

  it("shows a fixed reason by its code", () => {
    renderWithIntl(
      <StatusReason
        reason={{ text: "anything", code: "restarted", checks: [] }}
      />,
      { locale: "de" },
    );
    expect(
      screen.getByText(
        "Zurückgesetzt, weil ein Neustart der API die Verarbeitung unterbrochen hat.",
      ),
    ).toBeTruthy();
  });

  it("shows a user's reason, or an unknown code, as written", () => {
    renderWithIntl(
      <>
        <StatusReason
          reason={{ text: "Rückruf beim Lieferanten.", code: null, checks: [] }}
        />
        <StatusReason
          reason={{ text: "Something new.", code: "new_code", checks: [] }}
        />
      </>,
      { locale: "de" },
    );
    expect(screen.getByText(/Rückruf beim Lieferanten\./)).toBeTruthy();
    expect(screen.getByText(/Something new\./)).toBeTruthy();
  });
});
