import { expect, test } from "@playwright/test";

import { apiAs, invoiceXml, logIn, reviewerLogin, upload } from "./helpers";

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

  await page.getByLabel("Reject reason").fill("Looks like a duplicate.");
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(
    page.getByText("No decision possible while the invoice is rejected."),
  ).toBeVisible();

  const reason = "Not a duplicate: the supplier confirmed a second delivery.";
  await page.getByLabel("Reopen reason").fill(reason);
  await page.getByRole("button", { name: "Reopen" }).click();

  // Checked again and back in review: it can be approved or rejected again.
  await expect(
    page.getByRole("button", { name: "Approve", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Reopen reason")).toHaveCount(0);
  await expect(page.getByText("invoice.rejected")).toBeVisible();
  await expect(page.getByText("invoice.reopened")).toBeVisible();
  await expect(page.getByText(reason)).toBeVisible();
  // Processed twice: after the upload and after the reopen.
  await expect(page.getByText("processing → ready")).toHaveCount(2);
});
