/** Booking suggestions per invoice line (ADR-020): `GET /invoices/{id}/bookings`. */

export type BookingSource = {
  /** Null for imported history. */
  invoice_id: string | null;
  invoice_number: string | null;
  issue_date: string | null;
  supplier_name: string | null;
  text: string;
  account: string;
  same_supplier: boolean;
  similarity: number;
};

export type AccountSuggestion = {
  account: string;
  name: string;
  /** Share of the neighbours' weight, 0..1; not a probability. */
  share: number;
  sources: BookingSource[];
};

export type LineBooking = {
  line_no: number;
  text: string;
  method: "vector" | "text";
  suggestions: AccountSuggestion[];
  booked: {
    account: string;
    name: string;
    suggested_account: string | null;
  } | null;
};

export type Account = { number: string; name: string };

export type Bookings = {
  accounts: Account[];
  default_account: string;
  lines: LineBooking[];
};

export type BookingChoice = { line_no: number; account: string };

const FIELD = /^account-(\d+)$/;

/** The form field of a line's account select. */
export function accountField(lineNo: number): string {
  return `account-${lineNo}`;
}

/** The account a line's select starts with: the top suggestion, else the default account. */
export function preselected(line: LineBooking, defaultAccount: string): string {
  return line.suggestions[0]?.account ?? defaultAccount;
}

/** The chosen account per line from the approve form, in line order. */
export function bookingsFromForm(formData: FormData): BookingChoice[] {
  const choices: BookingChoice[] = [];
  for (const [name, value] of formData.entries()) {
    const match = FIELD.exec(name);
    if (match && typeof value === "string") {
      choices.push({ line_no: Number(match[1]), account: value });
    }
  }
  return choices.sort((a, b) => a.line_no - b.line_no);
}

/** "Suggested 0410 (92 %, by meaning) from MB-2025-0003, Muster GmbH" for the reviewer. */
export function suggestionNote(line: LineBooking): string {
  const top = line.suggestions[0];
  if (top === undefined) {
    return "No suggestion: no booked line to compare with.";
  }
  const how = line.method === "vector" ? "by meaning" : "by text match";
  const sources = top.sources
    .map((source) =>
      [source.invoice_number ?? "imported", source.supplier_name]
        .filter(Boolean)
        .join(", "),
    )
    .join("; ");
  return `Suggested ${top.account} ${top.name} (${Math.round(top.share * 100)} %, ${how}) from ${sources}.`;
}
