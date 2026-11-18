import { expect, test } from "@playwright/test";

import { invoiceXml, logIn, reviewerLogin } from "./helpers";

/**
 * The upload page (R2-7): a reviewer uploads an XRechnung XML, sees it checked and finds it in
 * the queue; the same file again is refused as a duplicate with a link to the first one.
 */

const run = Date.now().toString();
const file = `e2e-${run}-upload.xml`;

test("upload an XML invoice and find it in the queue", async ({ page }) => {
  const xml = await invoiceXml(
    "ubl_xrechnung.xml",
    "2026-IT-0815",
    `E2E-${run}-UP`,
  );
  await logIn(page, reviewerLogin());

  await page.getByRole("link", { name: "Upload", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Upload an invoice" }),
  ).toBeVisible();
  const chooser = page.getByLabel("Invoice file");
  await chooser.setInputFiles({
    name: file,
    mimeType: "application/xml",
    buffer: xml,
  });
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(
    page.getByText("All checks passed.", { exact: false }),
  ).toBeVisible({
    timeout: 60_000,
  });

  // The same file again: refused, with a link to the invoice it duplicates.
  await chooser.setInputFiles({
    name: file,
    mimeType: "application/xml",
    buffer: xml,
  });
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByText("This file was already uploaded.")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open the existing invoice" }),
  ).toBeVisible();

  // The new invoice waits in the review queue.
  await page.getByRole("link", { name: "← Queue" }).click();
  await expect(page.getByRole("link", { name: file })).toBeVisible();
  await page.getByRole("link", { name: file }).click();
  await expect(page.getByText("invoice.received")).toBeVisible();
});
