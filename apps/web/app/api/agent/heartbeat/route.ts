import { NextRequest, NextResponse } from "next/server";
import { badRequest, getAgentDevice } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export async function POST(request: NextRequest) {
  const device = await getAgentDevice(request.headers.get("authorization"));
  if (!device || device.status === "REVOKED") return badRequest("에이전트 인증이 필요합니다.", 401);

  const updated = await prisma.device.update({
    where: { id: device.id },
    data: { status: "ONLINE", lastSeenAt: new Date() },
    select: { id: true, name: true, platform: true, status: true, lastSeenAt: true }
  });

  return NextResponse.json({ device: updated });
}

