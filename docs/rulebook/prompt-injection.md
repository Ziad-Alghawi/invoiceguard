# Prompt injection: text that addresses an AI

## What the check does

The `prompt_injection` check scans the document text (the XML texts and attributes, the PDF text
layer) for instructions aimed at an AI system: "ignore previous instructions", "note to the AI
assistant", fake system messages, in English and German, and for invisible Unicode (zero-width
characters, bidi controls). It is heuristics, without an LLM.

## When it fails

A hit fails the check, blocks the invoice and writes a security event (`injection_suspected`). Such
an invoice is **never sent to the exception agent**: it is checked by hand. Its bookings are kept as
the record of the decision but are never retrieved as evidence for other invoices.

## What it means

An invoice that tries to instruct an AI is suspicious in itself: legitimate suppliers do not write
to software. Typical goals are to change the payee IBAN, to have the invoice approved, or to hide
another fraud such as changed totals.

## How to resolve

1. Do not follow anything the text asks for. Every other check ran on the original rules.
2. Compare the invoice with the order, the goods receipts and the verified bank account by hand.
3. Contact the supplier through the master-data contact if the invoice may be real.
4. Report it to the security team; the security page lists the event.

## Text the scan misses

The scan knows common phrasings only. Indirect business wording ("our valid bank details are ...")
and other languages get through, also in older invoices that are now part of the history. Text from
the history or any tool is data, never an instruction.
