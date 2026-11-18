import { expect, test } from "@playwright/test";

import { apiAs, invoiceXml, logIn, reviewerLogin, upload } from "./helpers";

/**
 * The exception agent (R2-6, ADR-018) in the browser: a blocked invoice with a changed IBAN
 * gets a finding and a German email draft to the supplier, and stays blocked.
 *
 * Without a model key (CI, the public demo) the "Investigate" button loads the recorded run for
 * this case. With a key (a local stack) the agent runs live after the upload; the page polls
 * until it is done.
 */

const run = Date.now().toString();
const changedIban = {
  number: `E2E-${run}-AGENT`,
  file: `e2e-${run}-agent.xml`,
};
// A live run takes about 10 to 20 seconds; the agent's own time limit is 90.
const AGENT_TIMEOUT_MS = 100_000;

type Investigation = { mode: "live" | "recorded" | "unavailable" };

let mode: Investigation["mode"];
let invoiceId: string;

test.beforeAll(async () => {
  const api = await apiAs(reviewerLogin());
  const xml = await invoiceXml(
    "ubl_fraud_iban.xml",
    "2026-IT-0816",
    changedIban.number,
  );
  expect(await upload(api, changedIban.file, xml)).toBe("blocked");
  const list = await api.get("/invoices?status=blocked&limit=200");
  const invoices = (await list.json()) as {
    id: string;
    original_filename: string;
  }[];
  invoiceId = invoices.find(
    (i) => i.original_filename === changedIban.file,
  )!.id;
  const response = await api.get(`/invoices/${invoiceId}/investigation`);
  mode = ((await response.json()) as Investigation).mode;
  await api.dispose();
});

test("a blocked invoice gets a finding and a German email draft", async ({
  page,
}) => {
  test.setTimeout(AGENT_TIMEOUT_MS + 30_000);
  expect(mode).not.toBe("unavailable");

  await logIn(page, reviewerLogin());
  await page.getByRole("link", { name: changedIban.file }).click();
  await expect(
    page.getByRole("heading", { name: "Investigation" }),
  ).toBeVisible();
  if (mode === "recorded") {
    await page.getByRole("button", { name: "Investigate" }).click();
    await expect(page.getByText(/recorded run from/)).toBeVisible();
  }

  await expect(page.getByRole("heading", { name: "Finding" })).toBeVisible({
    timeout: AGENT_TIMEOUT_MS,
  });
  await expect(page.getByText(/IBAN/).first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Email draft to the supplier/ }),
  ).toBeVisible();
  // To the address in the supplier master data, not the one on the invoice.
  await expect(
    page.getByText("To: buchhaltung@demo-it-service.example"),
  ).toBeVisible();
  await expect(page.getByText(/Mit freundlichen Grüßen/)).toBeVisible();
  // The agent proposes; the invoice is still blocked and waits for people.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    changedIban.file,
  );
  await expect(page.locator("main").getByText("blocked").first()).toBeVisible();
});
