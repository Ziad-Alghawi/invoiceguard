import { readFile } from "node:fs/promises";

import { type APIRequestContext, expect, test } from "@playwright/test";

import { apiAs, invoiceXml, logIn, reviewerLogin, upload } from "./helpers";

/**
 * The core story in the browser: log in, reject the changed-IBAN invoice, approve a clean one
 * and export it to DATEV. Approved invoices still waiting from earlier runs or manual testing
 * are exported through the API first, so the browser's export holds exactly this run's invoice
 * (one fiscal year per file would otherwise pick older ones first).
 */

const login = reviewerLogin();

const run = Date.now().toString();
const clean = {
  number: `E2E-${run}-OK`,
  file: `e2e-${run}-clean.xml`,
};
const fraud = {
  number: `E2E-${run}-FRAUD`,
  file: `e2e-${run}-fraud.xml`,
};

/** Exports whatever approved invoices are waiting, until the API says nothing is left. */
async function exportWaiting(api: APIRequestContext) {
  for (;;) {
    const response = await api.post("/exports/datev");
    if (response.status() === 409) {
      return;
    }
    expect(response.status(), await response.text()).toBe(201);
  }
}

test.beforeAll(async () => {
  const api = await apiAs(login);
  await exportWaiting(api);
  const cleanXml = await invoiceXml(
    "ubl_xrechnung.xml",
    "2026-IT-0815",
    clean.number,
  );
  const fraudXml = await invoiceXml(
    "ubl_fraud_iban.xml",
    "2026-IT-0816",
    fraud.number,
  );
  expect(await upload(api, fraud.file, fraudXml)).toBe("blocked");
  expect(await upload(api, clean.file, cleanXml)).toBe("ready");
  await api.dispose();
});

test("reject the fraud invoice, approve a clean one, export it to DATEV", async ({
  page,
}) => {
  await logIn(page, login);

  // The changed IBAN blocks the invoice; the reviewer rejects it with a reason.
  await page.getByRole("link", { name: fraud.file }).click();
  await expect(
    page.getByText(/Blocked by failed checks: iban\./),
  ).toBeVisible();
  const reason = "IBAN is not the supplier's verified account.";
  await page.getByLabel("Reject reason").fill(reason);
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(
    page.getByText("No decision possible while the invoice is rejected."),
  ).toBeVisible();
  await expect(page.getByText("invoice.rejected")).toBeVisible();
  await expect(page.getByText(reason).last()).toBeVisible();

  // The clean invoice passed every check and is approved without an override.
  await page.getByRole("link", { name: "← Queue" }).click();
  await page.getByRole("link", { name: clean.file }).click();
  // One SKR03 account per line (ADR-020), preselected with the suggestion; the reviewer decides.
  await page.getByLabel(/^1\. Notebook/).selectOption("0410");
  await page.getByLabel(/^2\. Einrichtung/).selectOption("4806");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(
    page.getByText("No decision possible while the invoice is approved."),
  ).toBeVisible();
  const api = await apiAs(login);
  const invoiceId = new URL(page.url()).pathname.split("/").at(-1);
  const booked = await api.get(`/invoices/${invoiceId}/bookings`);
  const lines = (await booked.json()).lines as {
    booked: { account: string };
  }[];
  expect(lines.map((line) => line.booked.account)).toEqual(["0410", "4806"]);
  await api.dispose();

  // Export: the booking file downloads and holds the approved invoice, not the rejected one.
  await page.getByRole("link", { name: "← Queue" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export to DATEV" }).click();
  await expect(page.getByRole("status")).toHaveText(
    /^Exported 1 invoice to DATEV\.Download again$/,
  );
  const file = await download;
  expect(file.suggestedFilename()).toMatch(
    /^EXTF_Buchungsstapel_\d{8}_\d{6}\.csv$/,
  );
  const csv = (await readFile(await file.path())).toString("latin1");
  expect(csv.startsWith('"EXTF";700;21;"Buchungsstapel";13;')).toBe(true);
  // One row per chosen account (issue #24): notebooks 3,747.00 and setup 570.00, both at 19 %.
  const rows = csv
    .split("\r\n")
    .filter((line) => line.includes(`"${clean.number}"`))
    .map((line) => line.split(";").slice(0, 11));
  const booking = (gross: string, account: string) => [
    gross,
    '"H"',
    '"EUR"',
    "",
    "",
    "",
    "70000",
    account,
    '"9"',
    "0511",
    `"${clean.number}"`,
  ];
  expect(rows).toEqual([booking("4458,93", "0410"), booking("678,30", "4806")]);
  expect(csv).not.toContain(fraud.number);
});
