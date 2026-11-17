import type { DemoLogin } from "@/lib/demo";

/** The public demo's shared logins, shown on purpose: the data is made up and reset daily. */
export function DemoCredentials({ logins }: { logins: DemoLogin[] }) {
  return (
    <section
      aria-label="Demo login"
      className="rounded-md border bg-muted/50 p-3 text-sm"
    >
      <p className="font-medium">Public demo accounts</p>
      {logins.map((login) => (
        <dl
          key={login.role}
          className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5"
        >
          <dt className="text-muted-foreground">Role</dt>
          <dd>{login.role}</dd>
          <dt className="text-muted-foreground">Email</dt>
          <dd className="font-mono break-all">{login.email}</dd>
          <dt className="text-muted-foreground">Password</dt>
          <dd className="font-mono break-all">{login.password}</dd>
        </dl>
      ))}
      <p className="mt-2 text-xs text-muted-foreground">
        A blocked invoice needs both: the reviewer requests an override, the
        approver confirms it. Here one visitor can use both accounts, so the
        demo shows the mechanism, not a real separation of duties. Made-up
        sample invoices, reset every night. Do not upload real data.
      </p>
    </section>
  );
}
