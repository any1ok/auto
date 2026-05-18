import { JobStatus } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { badRequest, getAgentDevice } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export async function POST(request: NextRequest) {
  const device = await getAgentDevice(request.headers.get("authorization"));
  if (!device || device.status === "REVOKED") return badRequest("에이전트 인증이 필요합니다.", 401);

  const now = new Date();
  await prisma.device.update({
    where: { id: device.id },
    data: { status: "ONLINE", lastSeenAt: now }
  });

  const job = await prisma.$transaction(async (tx) => {
    const candidate = await tx.messageJob.findFirst({
      where: {
        userId: device.userId,
        status: JobStatus.QUEUED,
        scheduledAt: { lte: now },
        OR: [{ deviceId: null }, { deviceId: device.id }]
      },
      orderBy: [{ scheduledAt: "asc" }, { createdAt: "asc" }]
    });

    if (!candidate) return null;

    const locked = await tx.messageJob.updateMany({
      where: { id: candidate.id, status: JobStatus.QUEUED },
      data: {
        status: JobStatus.LOCKED,
        deviceId: device.id,
        lockedAt: now,
        lockedByDeviceId: device.id,
        attempts: { increment: 1 },
        failureReason: null
      }
    });

    if (locked.count === 0) return null;

    return tx.messageJob.findUnique({
      where: { id: candidate.id },
      select: {
        id: true,
        recipientName: true,
        phone: true,
        kakaoRoomName: true,
        message: true,
        scheduledAt: true,
        attempts: true
      }
    });
  });

  return NextResponse.json({ job });
}

