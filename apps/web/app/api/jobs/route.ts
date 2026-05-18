import { JobStatus } from "@prisma/client";
import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { badRequest, normalizeString } from "@/lib/api";
import { prisma } from "@/lib/prisma";

const allowedCreateStatuses = new Set<JobStatus>([JobStatus.DRAFT, JobStatus.QUEUED]);
const allowedFilterStatuses = new Set<string>(Object.values(JobStatus));

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const statusParam = request.nextUrl.searchParams.get("status");
  const status = statusParam && allowedFilterStatuses.has(statusParam) ? (statusParam as JobStatus) : null;
  const jobs = await prisma.messageJob.findMany({
    where: {
      userId: user.id,
      ...(status ? { status } : {})
    },
    include: {
      device: { select: { id: true, name: true, status: true } },
      sendLogs: { orderBy: { createdAt: "desc" }, take: 3 }
    },
    orderBy: [{ scheduledAt: "desc" }, { createdAt: "desc" }]
  });

  return NextResponse.json({ jobs });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const body = await request.json().catch(() => null);
  const recipientId = normalizeString(body?.recipientId);
  const message = normalizeString(body?.message);
  const requestedStatus = normalizeString(body?.status) as JobStatus;
  const status = allowedCreateStatuses.has(requestedStatus) ? requestedStatus : JobStatus.QUEUED;
  const scheduledAt = body?.scheduledAt ? new Date(body.scheduledAt) : new Date();

  if (Number.isNaN(scheduledAt.getTime())) return badRequest("예약 시간이 올바르지 않습니다.");
  if (!message) return badRequest("메시지를 입력하세요.");

  const recipient = recipientId
    ? await prisma.recipient.findFirst({ where: { id: recipientId, userId: user.id } })
    : null;

  const recipientName = recipient?.name ?? normalizeString(body?.recipientName);
  const kakaoRoomName = recipient?.kakaoRoomName ?? normalizeString(body?.kakaoRoomName);
  const phone = (recipient?.phone ?? normalizeString(body?.phone)) || null;

  if (!recipientName) return badRequest("수신자 이름을 입력하세요.");
  if (!kakaoRoomName) return badRequest("카카오톡 방 이름을 입력하세요.");
  if (recipientId && !recipient) return badRequest("수신자를 찾을 수 없습니다.", 404);

  const job = await prisma.messageJob.create({
    data: {
      userId: user.id,
      recipientId: recipient?.id ?? null,
      recipientName,
      phone,
      kakaoRoomName,
      message,
      scheduledAt,
      status
    }
  });

  return NextResponse.json({ job }, { status: 201 });
}
