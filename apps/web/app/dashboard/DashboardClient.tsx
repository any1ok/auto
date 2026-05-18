"use client";

import { deviceStatusLabels, jobStatusLabels, type DeviceStatus, type JobStatus } from "@autosend/shared";
import { CalendarClock, CheckCircle2, CircleSlash, Computer, Download, LogOut, Plus, RefreshCw, Send } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type User = { id: string; email: string; name: string | null };
type Recipient = {
  id: string;
  name: string;
  phone: string | null;
  kakaoRoomName: string;
  consent: boolean;
  memo: string | null;
};
type Device = {
  id: string;
  name: string;
  platform: string | null;
  status: DeviceStatus;
  lastSeenAt: string | null;
  tokenLastFour: string | null;
  pairingExpiresAt: string | null;
};
type SendLog = {
  id: string;
  status: "SENT" | "FAILED";
  message: string | null;
  createdAt: string;
};
type Job = {
  id: string;
  recipientName: string;
  phone: string | null;
  kakaoRoomName: string;
  message: string;
  scheduledAt: string;
  status: JobStatus;
  failureReason: string | null;
  attempts: number;
  sentAt: string | null;
  device: { id: string; name: string; status: DeviceStatus } | null;
  sendLogs: SendLog[];
};

const statusFilters = ["ALL", "QUEUED", "LOCKED", "SENT", "FAILED", "CANCELLED"] as const;

export default function DashboardClient({ user }: { user: User }) {
  const router = useRouter();
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState<(typeof statusFilters)[number]>("ALL");
  const [notice, setNotice] = useState("");
  const [pairingCode, setPairingCode] = useState("");
  const [recipientForm, setRecipientForm] = useState({ name: "", phone: "", kakaoRoomName: "", memo: "" });
  const [jobForm, setJobForm] = useState({
    recipientId: "",
    recipientName: "",
    phone: "",
    kakaoRoomName: "",
    message: "",
    scheduledAt: ""
  });

  const selectedRecipient = useMemo(
    () => recipients.find((recipient) => recipient.id === jobForm.recipientId),
    [jobForm.recipientId, recipients]
  );

  const loadAll = useCallback(async (nextStatus = status) => {
    const [recipientsResponse, devicesResponse, jobsResponse] = await Promise.all([
      fetch("/api/recipients"),
      fetch("/api/devices"),
      fetch(`/api/jobs?status=${nextStatus}`)
    ]);

    if (recipientsResponse.ok) setRecipients((await recipientsResponse.json()).recipients);
    if (devicesResponse.ok) setDevices((await devicesResponse.json()).devices);
    if (jobsResponse.ok) setJobs((await jobsResponse.json()).jobs);
  }, [status]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  async function createRecipient(event: FormEvent) {
    event.preventDefault();
    setNotice("");
    const response = await fetch("/api/recipients", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...recipientForm, consent: true })
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setNotice(payload.error ?? "수신자를 만들 수 없습니다.");
      return;
    }
    setRecipientForm({ name: "", phone: "", kakaoRoomName: "", memo: "" });
    setNotice("수신자를 추가했습니다.");
    await loadAll();
  }

  async function createJob(event: FormEvent) {
    event.preventDefault();
    setNotice("");
    const payload = selectedRecipient
      ? {
          recipientId: selectedRecipient.id,
          message: jobForm.message,
          scheduledAt: jobForm.scheduledAt || undefined,
          status: "QUEUED"
        }
      : {
          recipientName: jobForm.recipientName,
          phone: jobForm.phone,
          kakaoRoomName: jobForm.kakaoRoomName,
          message: jobForm.message,
          scheduledAt: jobForm.scheduledAt || undefined,
          status: "QUEUED"
        };

    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      setNotice(result.error ?? "작업을 만들 수 없습니다.");
      return;
    }
    setJobForm({ recipientId: "", recipientName: "", phone: "", kakaoRoomName: "", message: "", scheduledAt: "" });
    setNotice("발송 작업을 대기열에 추가했습니다.");
    await loadAll();
  }

  async function createPairingCode() {
    setNotice("");
    const response = await fetch("/api/devices", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "내 PC", platform: navigator.platform })
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setNotice(payload.error ?? "페어링 코드를 만들 수 없습니다.");
      return;
    }
    setPairingCode(payload.pairingCode);
    setNotice("15분 동안 사용할 수 있는 페어링 코드를 만들었습니다.");
    await loadAll();
  }

  async function patchJob(id: string, action: "requeue" | "cancel") {
    const response = await fetch(`/api/jobs/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action })
    });
    const payload = await response.json().catch(() => ({}));
    setNotice(response.ok ? "작업 상태를 변경했습니다." : payload.error ?? "작업 상태를 변경할 수 없습니다.");
    await loadAll();
  }

  async function changeStatusFilter(nextStatus: (typeof statusFilters)[number]) {
    setStatus(nextStatus);
    await loadAll(nextStatus);
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">AutoSend</p>
          <h1>카카오톡 발송 관리</h1>
        </div>
        <div className="topbar-actions">
          <span className="muted">{user.email}</span>
          <Link href="/download" className="icon-link">
            <Download size={18} />
            다운로드
          </Link>
          <button onClick={logout} className="ghost-button" title="로그아웃">
            <LogOut size={18} />
            로그아웃
          </button>
        </div>
      </header>

      {notice ? <p className="notice">{notice}</p> : null}

      <section className="panel-grid">
        <form className="panel stack" onSubmit={createRecipient}>
          <div className="panel-title">
            <Plus size={18} />
            <h2>수신자</h2>
          </div>
          <div className="form-grid">
            <label>
              이름
              <input value={recipientForm.name} onChange={(event) => setRecipientForm({ ...recipientForm, name: event.target.value })} />
            </label>
            <label>
              전화번호
              <input value={recipientForm.phone} onChange={(event) => setRecipientForm({ ...recipientForm, phone: event.target.value })} />
            </label>
            <label>
              카카오톡 방 이름
              <input
                value={recipientForm.kakaoRoomName}
                onChange={(event) => setRecipientForm({ ...recipientForm, kakaoRoomName: event.target.value })}
              />
            </label>
            <label>
              메모
              <input value={recipientForm.memo} onChange={(event) => setRecipientForm({ ...recipientForm, memo: event.target.value })} />
            </label>
          </div>
          <button className="primary-button">
            <Plus size={16} />
            추가
          </button>
        </form>

        <form className="panel stack" onSubmit={createJob}>
          <div className="panel-title">
            <Send size={18} />
            <h2>발송 작업</h2>
          </div>
          <label>
            저장된 수신자
            <select value={jobForm.recipientId} onChange={(event) => setJobForm({ ...jobForm, recipientId: event.target.value })}>
              <option value="">직접 입력</option>
              {recipients.map((recipient) => (
                <option key={recipient.id} value={recipient.id}>
                  {recipient.name} / {recipient.kakaoRoomName}
                </option>
              ))}
            </select>
          </label>
          {!selectedRecipient ? (
            <div className="form-grid">
              <label>
                이름
                <input value={jobForm.recipientName} onChange={(event) => setJobForm({ ...jobForm, recipientName: event.target.value })} />
              </label>
              <label>
                카카오톡 방 이름
                <input value={jobForm.kakaoRoomName} onChange={(event) => setJobForm({ ...jobForm, kakaoRoomName: event.target.value })} />
              </label>
            </div>
          ) : null}
          <label>
            예약 시간
            <input
              value={jobForm.scheduledAt}
              onChange={(event) => setJobForm({ ...jobForm, scheduledAt: event.target.value })}
              type="datetime-local"
            />
          </label>
          <label>
            메시지
            <textarea value={jobForm.message} onChange={(event) => setJobForm({ ...jobForm, message: event.target.value })} rows={4} />
          </label>
          <button className="primary-button">
            <CalendarClock size={16} />
            대기열 추가
          </button>
        </form>

        <section className="panel stack">
          <div className="panel-title">
            <Computer size={18} />
            <h2>기기 페어링</h2>
          </div>
          <button onClick={createPairingCode} className="secondary-button">
            <RefreshCw size={16} />
            페어링 코드 생성
          </button>
          {pairingCode ? <div className="pairing-code">{pairingCode}</div> : null}
          <div className="device-list">
            {devices.map((device) => (
              <div className="device-row" key={device.id}>
                <div>
                  <strong>{device.name}</strong>
                  <span>{device.platform ?? "unknown"}</span>
                </div>
                <span className={`status-pill ${device.status.toLowerCase()}`}>{deviceStatusLabels[device.status]}</span>
              </div>
            ))}
          </div>
        </section>
      </section>

      <section className="table-panel">
        <div className="table-toolbar">
          <div>
            <h2>발송 작업</h2>
            <p className="muted">PC 앱이 대기 작업을 가져가면 처리 중 상태로 바뀝니다.</p>
          </div>
          <div className="segmented">
            {statusFilters.map((filter) => (
              <button key={filter} className={status === filter ? "active" : ""} onClick={() => void changeStatusFilter(filter)}>
                {filter === "ALL" ? "전체" : jobStatusLabels[filter as JobStatus]}
              </button>
            ))}
          </div>
        </div>
        <div className="notion-table">
          <div className="table-head table-row">
            <span>상태</span>
            <span>대상</span>
            <span>방 이름</span>
            <span>메시지</span>
            <span>예약</span>
            <span>기기</span>
            <span>작업</span>
          </div>
          {jobs.map((job) => (
            <div className="table-row" key={job.id}>
              <span className={`status-pill ${job.status.toLowerCase()}`}>{jobStatusLabels[job.status]}</span>
              <span>{job.recipientName}</span>
              <span>{job.kakaoRoomName}</span>
              <span className="message-cell">{job.message}</span>
              <span>{new Date(job.scheduledAt).toLocaleString()}</span>
              <span>{job.device?.name ?? "-"}</span>
              <span className="row-actions">
                {job.status === "SENT" || job.status === "FAILED" || job.status === "CANCELLED" ? (
                  <button onClick={() => void patchJob(job.id, "requeue")} className="icon-button" title="다시 대기열에 넣기">
                    <RefreshCw size={16} />
                  </button>
                ) : null}
                {job.status === "QUEUED" || job.status === "LOCKED" ? (
                  <button onClick={() => void patchJob(job.id, "cancel")} className="icon-button danger" title="취소">
                    <CircleSlash size={16} />
                  </button>
                ) : null}
                {job.status === "SENT" ? <CheckCircle2 className="success-icon" size={18} /> : null}
              </span>
              {job.failureReason ? <span className="failure-row">{job.failureReason}</span> : null}
            </div>
          ))}
          {jobs.length === 0 ? <div className="empty-state">작업이 없습니다.</div> : null}
        </div>
      </section>
    </main>
  );
}
