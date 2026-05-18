import { NextResponse } from "next/server";
import { hashSecret } from "@/lib/crypto";
import { prisma } from "@/lib/prisma";

export function badRequest(message: string, status = 400) {
  return NextResponse.json({ error: message }, { status });
}

export function normalizeString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export async function getAgentDevice(authorization: string | null) {
  if (!authorization?.startsWith("Bearer ")) return null;
  const token = authorization.slice("Bearer ".length).trim();
  if (!token) return null;
  const tokenHash = hashSecret(token);

  return prisma.device.findUnique({
    where: { agentTokenHash: tokenHash },
    include: { user: { select: { id: true, email: true } } }
  });
}

