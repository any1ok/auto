import { JobStatus } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { badRequest, normalizeString } from "@/lib/api";
import { prisma } from "@/lib/prisma";

type RouteContext = { params: Promise<{ id: string }> };

export async function PATCH(request: NextRequest, context: RouteContext) {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const { id } = await context.params;
  const body = await request.json().catch(() => null);
  const action = normalizeString(body?.action);

  if (action === "requeue") {
    const updated = await prisma.messageJob.updateMany({
      where: { id, userId: user.id },
      data: {
        status: JobStatus.QUEUED,
        failureReason: null,
        lockedAt: null,
        lockedByDeviceId: null,
        sentAt: null
      }
    });
    if (updated.count === 0) return badRequest("작업을 찾을 수 없습니다.", 404);
    return NextResponse.json({ job: await prisma.messageJob.findUnique({ where: { id } }) });
  }

  if (action === "cancel") {
    const updated = await prisma.messageJob.updateMany({
      where: { id, userId: user.id, status: { in: [JobStatus.DRAFT, JobStatus.QUEUED, JobStatus.LOCKED] } },
      data: { status: JobStatus.CANCELLED, lockedAt: null, lockedByDeviceId: null }
    });
    if (updated.count === 0) return badRequest("취소 가능한 작업을 찾을 수 없습니다.", 404);
    return NextResponse.json({ job: await prisma.messageJob.findUnique({ where: { id } }) });
  }

  const message = normalizeString(body?.message);
  const scheduledAt = body?.scheduledAt ? new Date(body.scheduledAt) : undefined;
  if (scheduledAt && Number.isNaN(scheduledAt.getTime())) return badRequest("예약 시간이 올바르지 않습니다.");

  const updated = await prisma.messageJob.updateMany({
    where: { id, userId: user.id, status: { in: [JobStatus.DRAFT, JobStatus.QUEUED] } },
    data: {
      ...(message ? { message } : {}),
      ...(scheduledAt ? { scheduledAt } : {}),
      ...(body?.status === JobStatus.DRAFT || body?.status === JobStatus.QUEUED ? { status: body.status } : {})
    }
  });

  if (updated.count === 0) return badRequest("수정 가능한 작업을 찾을 수 없습니다.", 404);
  return NextResponse.json({ job: await prisma.messageJob.findUnique({ where: { id } }) });
}

