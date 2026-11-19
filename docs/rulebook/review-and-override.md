# Review, override and reopen

## Statuses

- `ready`: every check passed or only warned; a reviewer may approve or reject.
- `blocked`: at least one check failed. It cannot be approved directly.
- `override_requested`: a reviewer asked to approve a blocked invoice with a written reason.
- `approved`, `rejected`: final decisions, written to the audit log (Prüfpfad, GoBD).

## Override of a blocked invoice (four eyes)

A blocked invoice may still be right, for example after the supplier confirmed a new IBAN by phone.
The four-eyes principle (Vier-Augen-Prinzip) applies:

1. A reviewer requests the override with a written reason that names the evidence (who confirmed
   what, when).
2. A second user with the approver role confirms or declines it. Nobody can confirm their own
   request.

The exception agent cannot approve, reject or override anything; it only proposes a finding and an
email draft.

## Reopen

A rejected invoice can be reopened with a reason, for example after the master data were corrected.
All checks run again on the current master data. Approved invoices cannot be reopened, because they
may already be exported for payment.

## Booking on approval

On approval the reviewer chooses an SKR03 account per line; the suggestion and its sources are shown.
The choice is stored with the decision and enters the booking history for later suggestions.

## Writing to the supplier

Emails go to the contact in the master data, never to an address printed on the invoice. Never
confirm bank details by email, and never write our verified bank details into an email.
