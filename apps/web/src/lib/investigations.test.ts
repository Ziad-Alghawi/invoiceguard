import { describe, expect, it } from "vitest";

import {
  emailText,
  formatSeconds,
  formatUsd,
  stepLabel,
} from "@/lib/investigations";
import { RUN, STEP } from "@/lib/investigations.fixture";

describe("investigation helpers", () => {
  it("formats small dollar amounts and durations", () => {
    expect(formatUsd("0.006008")).toBe("$0.006008");
    expect(formatSeconds(12091)).toBe("12.1 s");
    expect(formatSeconds(null)).toBe("–");
  });

  it("labels model and tool steps", () => {
    expect(stepLabel(RUN.steps[0])).toBe("Model: call tools");
    expect(stepLabel(RUN.steps[1])).toBe("check_iban(DE58876543210000000099)");
    expect(stepLabel({ ...STEP, result: null })).toBe("Model");
  });

  it("puts recipient, subject and body into the email text", () => {
    expect(emailText(RUN)).toBe(
      "To: buchhaltung@demo-it-service.example\nSubject: Rückfrage zu Rechnung 2026-IT-0816\n\nGuten Tag,\n\n...\n\nMit freundlichen Grüßen",
    );
    expect(emailText({ ...RUN, email_to: null }).startsWith("Subject:")).toBe(
      true,
    );
  });
});
