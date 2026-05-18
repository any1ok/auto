import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { badRequest, normalizeString } from "@/lib/api";
import { generatePairingCode, hashSecret } from "@/lib/crypto";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const devices = await prisma.device.findMany({
    where: { userId: user.id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ devices });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const body = await request.json().catch(() => null);
  const platform = normalizeString(body?.platform) || null;
  const name = normalizeString(body?.name) || "내 PC";
  const pairingCode = generatePairingCode();
  const pairingExpiresAt = new Date(Date.now() + 15 * 60 * 1000);

  const device = await prisma.device.create({
    data: {
      userId: user.id,
      name,
      platform,
      status: "PAIRING",
      pairingCodeHash: hashSecret(pairingCode),
      pairingExpiresAt
    }
  });

  return NextResponse.json(
    {
      device,
      pairingCode,
      expiresAt: pairingExpiresAt
    },
    { status: 201 }
  );
}

