import { CircleCheck, CircleX } from "lucide-react";

import type { ApiHealth } from "@/lib/health";
import { cn } from "@/lib/utils";

export function HealthStatus({ status }: { status: ApiHealth }) {
  const ok = status === "ok";
  const Icon = ok ? CircleCheck : CircleX;
  return (
    <p
      role="status"
      className={cn(
        "inline-flex w-fit items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium",
        ok
          ? "border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
          : "border-destructive/30 bg-destructive/10 text-destructive",
      )}
    >
      <Icon aria-hidden="true" className="size-4" />
      API: {status}
    </p>
  );
}
