import { expect, test } from "@playwright/test";

import {
  apiAs,
  approverLogin,
  history,
  invoiceXml,
  logIn,
  reviewerLogin,
  upload,
} from "./helpers";

/**
 * The four-eyes override (ADR-016) in the browser: the reviewer asks to approve the
 * changed-IBAN invoice with a reason and cannot finish it alone; a second person with the
 * approver role confirms it.
 */

const run = Date.now().toString();
const fraud = {
  number: `E2E-${run}-OVERRIDE`,
  file: `e2e-${run}-override.xml`,
};
const reviewer = reviewerLogin();
const approver = approverLogin();

test.beforeAll(async () => {
  const api = await apiAs(reviewer);
  const xml = await invoiceXml(
    "ubl_fraud_iban.xml",
    "2026-IT-0816",
    fraud.number,
  );
  expect(await upload(api, fraud.file, xml)).toBe("blocked");
  await api.dispose();
});

test("a reviewer requests an override and a second person approves it", async ({
  page,
}) => {
  // The reviewer: a blocked invoice cannot be approved directly, only an override requested.
  await logIn(page, reviewer);
  await expect(page.getByText("· Prüfer")).toBeVisible();
  await page.getByRole("link", { name: fraud.file }).click();
  await expect(
    page.getByText(/Gesperrt durch fehlgeschlagene Prüfungen: IBAN\./),
  ).toBeVisible();
  // The status reason under the title and in the history, in German (ADR-027).
  await expect(
    page.getByText("Fehlgeschlagene Prüfungen: IBAN.").first(),
  ).toBeVisible();
  await expect(page.getByRole("main")).not.toContainText("Failed checks");
  await expect(
    page.getByRole("button", { name: "Freigeben", exact: true }),
  ).toHaveCount(0);
  const reason = "IBAN change confirmed by phone with the supplier.";
  await page.getByLabel("Begründung der Ausnahme").fill(reason);
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Ausnahmefreigabe beantragen" })
    .click();
  await expect(
    page.getByText(`Ausnahmefreigabe beantragt von ${reviewer.email}`),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Nur ein Benutzer mit der Rolle Freigeber kann sie bestätigen oder ablehnen.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Ausnahme bestätigen" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Abmelden" }).click();

  // The approver: a different person confirms, with a reason of their own.
  await logIn(page, approver);
  await expect(page.getByText("· Freigeber")).toBeVisible();
  await page.getByRole("link", { name: fraud.file }).click();
  const note = "Checked the call notes and the new bank letter.";
  await page.getByLabel("Begründung des Freigebers").fill(note);
  await page.getByRole("button", { name: "Ausnahme bestätigen" }).click();
  await expect(
    page.getByText(
      "Keine Entscheidung möglich, solange die Rechnung freigegeben ist.",
    ),
  ).toBeVisible();
  // The audit history (exact: the paragraph above also says "beantragt von").
  await expect(
    history(page).getByText("Ausnahmefreigabe beantragt", { exact: true }),
  ).toBeVisible();
  await expect(
    history(page).getByText("Ausnahmefreigabe bestätigt", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(note).last()).toBeVisible();
});
