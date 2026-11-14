import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the running Docker Compose stack (`make dev`, `make seed`,
 * `make seed-user`); run them with `make e2e`. No LLM is called: the tests upload XML invoices.
 */
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // No retries: a flaky end-to-end test should be seen, not hidden.
  retries: 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"]],
  use: {
    baseURL: process.env.E2E_WEB_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
