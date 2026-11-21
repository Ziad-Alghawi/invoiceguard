import { expect, test } from "@playwright/test";

import {
  apiAs,
  history,
  invoiceXml,
  logIn,
  reviewerLogin,
  upload,
} from "./helpers";

/**
 * Reopening (ADR-016): a reviewer rejects a clean invoice, then reopens it with a reason; the
 * checks run again, it is back in review and the history shows both decisions.
 */

const login = reviewerLogin();
const run = Date.now().toString();
const file = `e2e-${run}-reopen.xml`;

test.beforeAll(async () => {
  const api = await apiAs(login);
  const xml = await invoiceXml(
    "ubl_xrechnung.xml",
    "2026-IT-0815",
    `E2E-${run}-RE`,
  );
  expect(await upload(api, file, xml)).toBe("ready");
  await api.dispose();
});

test("reject an invoice and reopen it", async ({ page }) => {
  await logIn(page, login);
  await page.getByRole("link", { name: file }).click();

  await page.getByLabel("Grund der Ablehnung").fill("Looks like a duplicate.");
  await page.getByRole("button", { name: "Ablehnen" }).click();
  await expect(
    page.getByText(
      "Keine Entscheidung möglich, solange die Rechnung abgelehnt ist.",
    ),
  ).toBeVisible();

  const reason = "Not a duplicate: the supplier confirmed a second delivery.";
  await page.getByLabel("Grund für das Wiederöffnen").fill(reason);
  await page.getByRole("button", { name: "Wieder öffnen" }).click();

  // Checked again and back in review: it can be approved or rejected again.
  await expect(
    page.getByRole("button", { name: "Freigeben", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Grund für das Wiederöffnen")).toHaveCount(0);
  // Audit actions; exact, so the lower-case status badges do not match.
  await expect(
    history(page).getByText("Abgelehnt", { exact: true }),
  ).toBeVisible();
  await expect(
    history(page).getByText("Wieder geöffnet", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(reason)).toBeVisible();
  // Processed twice: after the upload and after the reopen.
  await expect(page.getByText("in Bearbeitung → bereit")).toHaveCount(2);
});
