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
  const data = {
    name: normalizeString(body?.name),
    kakaoRoomName: normalizeString(body?.kakaoRoomName),
    phone: normalizeString(body?.phone) || null,
    memo: normalizeString(body?.memo) || null,
    consent: typeof body?.consent === "boolean" ? body.consent : true
  };

  if (!data.name) return badRequest("수신자 이름을 입력하세요.");
  if (!data.kakaoRoomName) return badRequest("카카오톡 방 이름을 입력하세요.");

  const updated = await prisma.recipient.updateMany({
    where: { id, userId: user.id },
    data
  });

  if (updated.count === 0) return badRequest("수신자를 찾을 수 없습니다.", 404);
  const recipient = await prisma.recipient.findUnique({ where: { id } });
  return NextResponse.json({ recipient });
}

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const { id } = await context.params;
  const deleted = await prisma.recipient.deleteMany({
    where: { id, userId: user.id }
  });

  if (deleted.count === 0) return badRequest("수신자를 찾을 수 없습니다.", 404);
  return NextResponse.json({ ok: true });
}

