import { NextRequest, NextResponse } from "next/server";
import { badRequest, normalizeString } from "@/lib/api";
import { generateAgentToken, hashSecret } from "@/lib/crypto";
import { prisma } from "@/lib/prisma";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const pairingCode = normalizeString(body?.pairingCode);
  const name = normalizeString(body?.name);
  const platform = normalizeString(body?.platform);

  if (!pairingCode) return badRequest("페어링 코드를 입력하세요.");

  const device = await prisma.device.findUnique({
    where: { pairingCodeHash: hashSecret(pairingCode) }
  });

  if (!device || device.status !== "PAIRING" || !device.pairingExpiresAt || device.pairingExpiresAt < new Date()) {
    return badRequest("페어링 코드가 만료되었거나 올바르지 않습니다.", 401);
  }

  const token = generateAgentToken();
  const updated = await prisma.device.update({
    where: { id: device.id },
    data: {
      name: name || device.name,
      platform: platform || device.platform,
      status: "ONLINE",
      pairingCodeHash: null,
      pairingExpiresAt: null,
      agentTokenHash: hashSecret(token),
      tokenLastFour: token.slice(-4),
      lastSeenAt: new Date()
    },
    select: {
      id: true,
      name: true,
      platform: true,
      status: true,
      lastSeenAt: true
    }
  });

  return NextResponse.json({ token, device: updated });
}

