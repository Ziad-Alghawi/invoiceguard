export type DemoLogin = { email: string; password: string };

/**
 * The shared demo account (ADR-006, ADR-014) from the server-only `DEMO_LOGIN_EMAIL` and
 * `DEMO_LOGIN_PASSWORD` variables, read per request. Unset outside the public demo: then the
 * login page shows no credentials.
 */
export function getDemoLogin(): DemoLogin | null {
  const email = process.env.DEMO_LOGIN_EMAIL;
  const password = process.env.DEMO_LOGIN_PASSWORD;
  if (!email || !password) {
    return null;
  }
  return { email, password };
}
