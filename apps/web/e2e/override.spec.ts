import { expect, test } from "@playwright/test";

import {
  apiAs,
  approverLogin,
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
  await expect(page.getByText("· reviewer")).toBeVisible();
  await page.getByRole("link", { name: fraud.file }).click();
  await expect(
    page.getByText(/Blocked by failed checks: iban\./),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve", exact: true }),
  ).toHaveCount(0);
  const reason = "IBAN change confirmed by phone with the supplier.";
  await page.getByLabel("Override reason").fill(reason);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Request override" }).click();
  await expect(
    page.getByText(`Override requested by ${reviewer.email}`),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Only a user with the approver role can confirm or decline it.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Confirm override" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Log out" }).click();

  // The approver: a different person confirms, with a reason of their own.
  await logIn(page, approver);
  await expect(page.getByText("· approver")).toBeVisible();
  await page.getByRole("link", { name: fraud.file }).click();
  const note = "Checked the call notes and the new bank letter.";
  await page.getByLabel("Approver reason").fill(note);
  await page.getByRole("button", { name: "Confirm override" }).click();
  await expect(
    page.getByText("No decision possible while the invoice is approved."),
  ).toBeVisible();
  await expect(page.getByText("invoice.override_requested")).toBeVisible();
  await expect(page.getByText("invoice.override_confirmed")).toBeVisible();
  await expect(page.getByText(note).last()).toBeVisible();
});
