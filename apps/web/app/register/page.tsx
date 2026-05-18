"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, email, password })
    });

    const payload = await response.json().catch(() => ({}));
    setLoading(false);

    if (!response.ok) {
      setError(payload.error ?? "회원가입에 실패했습니다.");
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
          <h1>계정 만들기</h1>
        </div>
        <form onSubmit={submit} className="stack">
          <label>
            이름
            <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" />
          </label>
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
              autoComplete="new-password"
            />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
          <button disabled={loading} className="primary-button">
            {loading ? "생성 중" : "회원가입"}
          </button>
        </form>
        <p className="muted">
          이미 계정이 있으면 <Link href="/login">로그인</Link>
        </p>
      </section>
    </main>
  );
}

