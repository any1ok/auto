"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password })
    });

    const payload = await response.json().catch(() => ({}));
    setLoading(false);

    if (!response.ok) {
      setError(payload.error ?? "로그인에 실패했습니다.");
      return;
    }

    router.replace("/dashboard");
    router.refresh();
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <div>
          <p className="eyebrow">AutoSend</p>
          <h1>관리 웹 로그인</h1>
        </div>
        <form onSubmit={submit} className="stack">
          <label>
            이메일
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" />
          </label>
          <label>
            비밀번호
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
            />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
          <button disabled={loading} className="primary-button">
            {loading ? "확인 중" : "로그인"}
          </button>
        </form>
        <p className="muted">
          계정이 없으면 <Link href="/register">회원가입</Link>
        </p>
      </section>
    </main>
  );
}

