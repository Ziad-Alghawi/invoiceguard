import type { DemoLogin } from "@/lib/demo";

/** The public demo's shared login, shown on purpose: the data is made up and reset daily. */
export function DemoCredentials({ login }: { login: DemoLogin }) {
  return (
    <section
      aria-label="Demo login"
      className="rounded-md border bg-muted/50 p-3 text-sm"
    >
      <p className="font-medium">Public demo account</p>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        <dt className="text-muted-foreground">Email</dt>
        <dd className="font-mono break-all">{login.email}</dd>
        <dt className="text-muted-foreground">Password</dt>
        <dd className="font-mono break-all">{login.password}</dd>
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        Made-up sample invoices, reset every night. Do not upload real data.
      </p>
    </section>
  );
}
