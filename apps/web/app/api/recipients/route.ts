import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { badRequest, normalizeString } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const recipients = await prisma.recipient.findMany({
    where: { userId: user.id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ recipients });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return badRequest("로그인이 필요합니다.", 401);

  const body = await request.json().catch(() => null);
  const name = normalizeString(body?.name);
  const kakaoRoomName = normalizeString(body?.kakaoRoomName);
  const phone = normalizeString(body?.phone);
  const memo = normalizeString(body?.memo);
  const consent = typeof body?.consent === "boolean" ? body.consent : true;

  if (!name) return badRequest("수신자 이름을 입력하세요.");
  if (!kakaoRoomName) return badRequest("카카오톡 방 이름을 입력하세요.");

  try {
    const recipient = await prisma.recipient.create({
      data: {
        userId: user.id,
        name,
        kakaoRoomName,
        phone: phone || null,
        memo: memo || null,
        consent
      }
    });

    return NextResponse.json({ recipient }, { status: 201 });
  } catch {
    return badRequest("같은 카카오톡 방 이름의 수신자가 이미 있습니다.", 409);
  }
}

