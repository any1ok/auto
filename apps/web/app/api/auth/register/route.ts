import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, sessionCookieOptions, signSession } from "@/lib/auth";
import { badRequest, normalizeString } from "@/lib/api";
import { hashPassword } from "@/lib/crypto";
import { prisma } from "@/lib/prisma";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = normalizeString(body?.email).toLowerCase();
  const name = normalizeString(body?.name);
  const password = normalizeString(body?.password);

  if (!email || !email.includes("@")) return badRequest("유효한 이메일을 입력하세요.");
  if (password.length < 8) return badRequest("비밀번호는 8자 이상이어야 합니다.");

  try {
    const user = await prisma.user.create({
      data: {
        email,
        name: name || null,
        passwordHash: await hashPassword(password)
      },
      select: { id: true, email: true, name: true }
    });

    const token = await signSession(user.id);
    const response = NextResponse.json({ user });
    response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions());
    return response;
  } catch {
    return badRequest("이미 가입된 이메일이거나 계정을 만들 수 없습니다.", 409);
  }
}

