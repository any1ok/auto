import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, sessionCookieOptions, signSession } from "@/lib/auth";
import { badRequest, normalizeString } from "@/lib/api";
import { verifyPassword } from "@/lib/crypto";
import { prisma } from "@/lib/prisma";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = normalizeString(body?.email).toLowerCase();
  const password = normalizeString(body?.password);

  if (!email || !password) return badRequest("이메일과 비밀번호를 입력하세요.");

  const user = await prisma.user.findUnique({ where: { email } });
  if (!user || !(await verifyPassword(password, user.passwordHash))) {
    return badRequest("이메일 또는 비밀번호가 올바르지 않습니다.", 401);
  }

  const token = await signSession(user.id);
  const response = NextResponse.json({
    user: { id: user.id, email: user.email, name: user.name }
  });
  response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions());
  return response;
}

