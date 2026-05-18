import { JobStatus, SendLogStatus } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { badRequest, getAgentDevice, normalizeString } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export async function POST(request: NextRequest) {
  const device = await getAgentDevice(request.headers.get("authorization"));
  if (!device || device.status === "REVOKED") return badRequest("에이전트 인증이 필요합니다.", 401);

  const body = await request.json().catch(() => null);
  const jobId = normalizeString(body?.jobId);
  const status = normalizeString(body?.status) as SendLogStatus;
  const message = normalizeString(body?.message);
  const screenshotPath = normalizeString(body?.screenshotPath);

  if (!jobId) return badRequest("작업 ID가 필요합니다.");
  if (status !== SendLogStatus.SENT && status !== SendLogStatus.FAILED) {
    return badRequest("결과 상태가 올바르지 않습니다.");
  }

  const job = await prisma.messageJob.findFirst({
    where: { id: jobId, userId: device.userId }
  });

  if (!job) return badRequest("작업을 찾을 수 없습니다.", 404);
  if (job.lockedByDeviceId && job.lockedByDeviceId !== device.id) {
    return badRequest("다른 기기에서 처리 중인 작업입니다.", 409);
  }

  const updated = await prisma.$transaction(async (tx) => {
    const nextStatus = status === SendLogStatus.SENT ? JobStatus.SENT : JobStatus.FAILED;
    const updatedJob = await tx.messageJob.update({
      where: { id: job.id },
      data: {
        status: nextStatus,
        failureReason: status === SendLogStatus.FAILED ? message || "발송 실패" : null,
        sentAt: status === SendLogStatus.SENT ? new Date() : null,
        lockedAt: null,
        lockedByDeviceId: null,
        deviceId: device.id
      }
    });

    await tx.sendLog.create({
      data: {
        userId: device.userId,
        jobId: job.id,
        deviceId: device.id,
        status,
        message: message || null,
        screenshotPath: screenshotPath || null
      }
    });

    return updatedJob;
  });

  await prisma.device.update({
    where: { id: device.id },
    data: { status: "ONLINE", lastSeenAt: new Date() }
  });

  return NextResponse.json({ job: updated });
}
