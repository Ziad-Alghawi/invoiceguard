import { describe, expect, it } from "vitest";

import {
  emailText,
  formatSeconds,
  formatUsd,
  modelAction,
  toolCall,
} from "@/lib/investigations";
import { RUN, STEP } from "@/lib/investigations.fixture";

const LABELS = {
  to: (to: string) => `To: ${to}`,
  subject: (subject: string) => `Subject: ${subject}`,
};

describe("investigation helpers", () => {
  it("formats small dollar amounts and durations in the UI language", () => {
    expect(formatUsd("0.006008", "en")).toBe("$0.006008");
    expect(formatUsd("0.006008", "de")).toBe("0,006008 $");
    expect(formatSeconds(12091, "en")).toBe("12.1 s");
    expect(formatSeconds(12091, "de")).toBe("12,1 s");
    expect(formatSeconds(null, "en")).toBe("–");
  });

  it("names a model step's action and a tool step's call", () => {
    expect(modelAction(RUN.steps[0])).toBe("call tools");
    expect(modelAction({ ...STEP, result: null })).toBeNull();
    expect(toolCall(RUN.steps[1])).toBe("check_iban(DE58876543210000000099)");
  });

  it("puts recipient, subject and body into the email text", () => {
    expect(emailText(RUN, LABELS)).toBe(
      "To: buchhaltung@demo-it-service.example\nSubject: Rückfrage zu Rechnung 2026-IT-0816\n\nGuten Tag,\n\n...\n\nMit freundlichen Grüßen",
    );
    expect(
      emailText({ ...RUN, email_to: null }, LABELS).startsWith("Subject:"),
    ).toBe(true);
  });
});
