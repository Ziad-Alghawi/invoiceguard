import { StatusBadge } from "@/components/status-badge";
import type { InvoiceCheck } from "@/lib/invoices";

/** Check results, worst first (the API's order), with their evidence on demand. */
export function CheckList({ checks }: { checks: InvoiceCheck[] }) {
  if (checks.length === 0) {
    return <p className="text-sm text-muted-foreground">No checks run yet.</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {checks.map((check) => (
        <li key={check.type} className="rounded-md border p-3 text-sm">
          <div className="flex items-center gap-2">
            <StatusBadge status={check.status} />
            <span className="font-medium">
              {check.type.replaceAll("_", " ")}
            </span>
          </div>
          <p className="mt-1">{check.message}</p>
          {Object.keys(check.evidence).length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                Evidence
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs">
                {JSON.stringify(check.evidence, null, 2)}
              </pre>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}
