import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  type APIRequestContext,
  expect,
  request,
  test,
} from "@playwright/test";

/**
 * The core story in the browser: log in, reject the changed-IBAN invoice, approve a clean one
 * and export it to DATEV. The invoices are uploaded through the API first (the UI has no upload
 * page yet), each with an invoice number unique to this run, so the test can run again on the
 * same stack without hitting the duplicate checks. Approved invoices still waiting from earlier
 * runs or manual testing are exported through the API first, so the browser's export holds
 * exactly this run's invoice (one fiscal year per file would otherwise pick older ones first).
 */

const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";
const FIXTURES = path.join(__dirname, "..", "..", "api", "tests", "fixtures");
const PROCESSING_TIMEOUT_MS = 60_000;

function env(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set: run the tests with \`make e2e\``);
  }
  return value;
}

const EMAIL = env("INVOICEGUARD_SEED_USER_EMAIL");
const PASSWORD = env("INVOICEGUARD_SEED_USER_PASSWORD");

const run = Date.now().toString();
const clean = {
  number: `E2E-${run}-OK`,
  file: `e2e-${run}-clean.xml`,
};
const fraud = {
  number: `E2E-${run}-FRAUD`,
  file: `e2e-${run}-fraud.xml`,
};

/** A fixture with another invoice number (BT-1). */
async function invoiceXml(fixture: string, from: string, to: string) {
  const xml = await readFile(path.join(FIXTURES, fixture), "utf-8");
  const changed = xml.replace(
    `<cbc:ID>${from}</cbc:ID>`,
    `<cbc:ID>${to}</cbc:ID>`,
  );
  expect(changed).not.toBe(xml);
  return Buffer.from(changed, "utf-8");
}

/** Uploads an invoice and waits until processing has finished; returns its status. */
async function upload(api: APIRequestContext, name: string, xml: Buffer) {
  const response = await api.post("/invoices", {
    multipart: { file: { name, mimeType: "application/xml", buffer: xml } },
  });
  expect(response.status(), await response.text()).toBe(202);
  const { id } = (await response.json()) as { id: string };
  let status = "received";
  await expect
    .poll(
      async () => {
        const detail = await api.get(`/invoices/${id}`);
        status = ((await detail.json()) as { status: string }).status;
        return status;
      },
      { timeout: PROCESSING_TIMEOUT_MS },
    )
    .not.toMatch(/^(received|processing)$/);
  return status;
}

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
  const api = await request.newContext({ baseURL: API_URL });
  const login = await api.post("/auth/login", {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(login.status(), await login.text()).toBe(200);
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
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(
    page.getByRole("heading", { name: "Invoice queue" }),
  ).toBeVisible();

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
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(
    page.getByText("No decision possible while the invoice is approved."),
  ).toBeVisible();

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
  const row = csv
    .split("\r\n")
    .find((line) => line.includes(`"${clean.number}"`));
  expect(row?.split(";").slice(0, 11)).toEqual([
    "5137,23",
    '"H"',
    '"EUR"',
    "",
    "",
    "",
    "70000",
    "4900",
    '"9"',
    "0511",
    `"${clean.number}"`,
  ]);
  expect(csv).not.toContain(fraud.number);
});
