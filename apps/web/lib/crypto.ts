import { createHash, randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";

export function hashSecret(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function generatePairingCode(): string {
  return String(Math.floor(100000 + Math.random() * 900000));
}

export function generateAgentToken(): string {
  return randomBytes(32).toString("base64url");
}

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, 12);
}

export async function verifyPassword(password: string, passwordHash: string): Promise<boolean> {
  return bcrypt.compare(password, passwordHash);
}

