import { describe, expect, it } from "vitest";
import { generateAgentToken, generatePairingCode, hashSecret } from "../lib/crypto";

describe("crypto helpers", () => {
  it("hashes secrets deterministically without exposing the original value", () => {
    const first = hashSecret("123456");
    const second = hashSecret("123456");

    expect(first).toBe(second);
    expect(first).not.toContain("123456");
    expect(first).toHaveLength(64);
  });

  it("generates six digit pairing codes", () => {
    expect(generatePairingCode()).toMatch(/^\d{6}$/);
  });

  it("generates long random agent tokens", () => {
    expect(generateAgentToken().length).toBeGreaterThan(30);
  });
});
