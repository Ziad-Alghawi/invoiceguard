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

/** The values of the "Suggested 0410 … (92 %, by meaning) from MB-2025-0003, Muster GmbH" note. */
export type SuggestionNote = {
  account: string;
  name: string;
  share: number;
  method: LineBooking["method"];
  sources: string;
};

/**
 * What the reviewer reads about a line's suggestion, or null without one. `imported` names a
 * source from imported history, which has no invoice number.
 */
export function suggestionNote(
  line: LineBooking,
  imported: string,
): SuggestionNote | null {
  const top = line.suggestions[0];
  if (top === undefined) {
    return null;
  }
  const sources = top.sources
    .map((source) =>
      [source.invoice_number ?? imported, source.supplier_name]
        .filter(Boolean)
        .join(", "),
    )
    .join("; ");
  return {
    account: top.account,
    name: top.name,
    share: Math.round(top.share * 100),
    method: line.method,
    sources,
  };
}
