import { deviceStatusLabels, jobStatusLabels, type AgentJob, type DeviceStatus } from "@autosend/shared";
import { Check, CircleSlash, KeyRound, RefreshCw, Send, Server, ShieldAlert } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import type { AutomationPermissionStatus, AutomationResult, StoredConfig } from "../../main/types";

function platformName() {
  return `${navigator.platform || "desktop"} / ${navigator.userAgent.includes("Windows") ? "Windows" : navigator.userAgent.includes("Mac") ? "macOS" : "Unknown"}`;
}

export default function App() {
  const [config, setConfig] = useState<StoredConfig>({ serverUrl: "http://localhost:3000", token: null, device: null });
  const [serverUrl, setServerUrl] = useState("http://localhost:3000");
  const [pairingCode, setPairingCode] = useState("");
  const [pendingJob, setPendingJob] = useState<AgentJob | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [permissions, setPermissions] = useState<AutomationPermissionStatus | null>(null);
  const [awaitingSendConfirmation, setAwaitingSendConfirmation] = useState(false);
  const [lastAutomationResult, setLastAutomationResult] = useState<AutomationResult | null>(null);

  const connected = Boolean(config.token && config.device);

  async function refreshConfig() {
    const nextConfig = await window.autosend.getConfig();
    setConfig(nextConfig);
    setServerUrl(nextConfig.serverUrl);
  }

  async function refreshPermissions() {
    const nextPermissions = await window.autosend.checkPermissions();
    setPermissions(nextPermissions);
    return nextPermissions;
  }

  async function requestPermissions(includeScreenRecording = false) {
    setBusy(true);
    setNotice("macOS 권한 요청을 보냅니다. 시스템 대화상자가 뜨면 허용하세요.");
    try {
      const nextPermissions = await window.autosend.requestPermissions(includeScreenRecording);
      setPermissions(nextPermissions);
      setNotice(
        nextPermissions.ok
          ? "필수 권한이 준비되었습니다."
          : "권한 요청을 보냈습니다. 허용 후 AutoSend를 완전히 재시작하세요."
      );
      return nextPermissions;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "권한을 요청할 수 없습니다.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refreshConfig();
    void refreshPermissions();
  }, []);

  useEffect(() => {
    if (!connected) return;

    let stopped = false;
    async function tick() {
      try {
        const device = await window.autosend.heartbeat();
        setConfig((current) => ({ ...current, device }));
        if (!pendingJob && !awaitingSendConfirmation) {
          const job = await window.autosend.claimJob();
          if (!stopped && job) {
            setPendingJob(job);
            setNotice("새 발송 작업을 가져왔습니다. 실제 발송 전 내용을 확인하세요.");
          }
        }
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "서버 연결에 실패했습니다.");
      }
    }

    void tick();
    const timer = window.setInterval(() => void tick(), 12000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [awaitingSendConfirmation, connected, pendingJob]);

  async function pair(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      const nextConfig = await window.autosend.pair({
        serverUrl,
        pairingCode,
        name: "AutoSend PC",
        platform: platformName()
      });
      setConfig(nextConfig);
      setPairingCode("");
      setNotice("기기 페어링이 완료되었습니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "페어링에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function saveServerUrl() {
    const nextConfig = await window.autosend.saveConfig({ serverUrl });
    setConfig(nextConfig);
    setNotice("서버 URL을 저장했습니다.");
  }

  async function claimNow() {
    setBusy(true);
    setNotice("");
    try {
      const job = await window.autosend.claimJob();
      setPendingJob(job);
      setNotice(job ? "발송 작업을 가져왔습니다." : "대기 중인 작업이 없습니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "작업을 가져올 수 없습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function runCurrentJob() {
    if (!pendingJob) return;
    setBusy(true);
    setNotice("자동 발송을 실행합니다.");
    try {
      const currentPermissions = await refreshPermissions();
      if (!currentPermissions.ok) {
        const requestedPermissions = await requestPermissions(false);
        if (!requestedPermissions?.ok) {
          setNotice("손쉬운 사용/자동화 권한을 허용한 뒤 AutoSend를 완전히 재시작하고 다시 발송하세요.");
          return;
        }
      }

      const result = await window.autosend.runAutomation({ job: pendingJob, dryRun: false });
      setLastAutomationResult(result);
      if (!result.ok || !result.sent) {
        await window.autosend.sendResult({
          jobId: pendingJob.id,
          status: "FAILED",
          message: result.error ?? "자동화 실패"
        });
        setPendingJob(null);
        setAwaitingSendConfirmation(false);
        setNotice("실패 결과를 서버에 기록했습니다.");
        return;
      }

      setAwaitingSendConfirmation(true);
      setNotice("자동화 입력이 끝났습니다. 카카오톡 화면에서 실제 발송 여부를 확인하고 결과를 기록하세요.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "자동화 실행에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function recordSendResult(status: "SENT" | "FAILED") {
    if (!pendingJob) return;
    setBusy(true);
    try {
      await window.autosend.sendResult({
        jobId: pendingJob.id,
        status,
        message: status === "SENT" ? "사용자가 카카오톡 실제 발송을 확인했습니다." : "사용자가 카카오톡 실제 미발송을 확인했습니다."
      });
      setPendingJob(null);
      setAwaitingSendConfirmation(false);
      setNotice(status === "SENT" ? "성공 결과를 서버에 기록했습니다." : "실패 결과를 서버에 기록했습니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "결과를 기록할 수 없습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function rejectJob() {
    if (!pendingJob) return;
    setBusy(true);
    try {
      await window.autosend.sendResult({
        jobId: pendingJob.id,
        status: "FAILED",
        message: "사용자가 최종 확인 단계에서 취소했습니다."
      });
        setPendingJob(null);
        setAwaitingSendConfirmation(false);
        setNotice("취소 결과를 서버에 기록했습니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "취소 결과를 기록할 수 없습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">AutoSend Desktop</p>
          <h1>카카오톡 발송 보조 앱</h1>
        </div>
        <span className={`status-pill ${(config.device?.status ?? "OFFLINE").toLowerCase()}`}>
          {connected ? deviceStatusLabels[config.device!.status as DeviceStatus] : "미연결"}
        </span>
      </header>

      {notice ? <p className="notice">{notice}</p> : null}

      <section className="grid">
        <form className="panel stack" onSubmit={pair}>
          <div className="panel-title">
            <KeyRound size={18} />
            <h2>페어링</h2>
          </div>
          <label>
            서버 URL
            <input value={serverUrl} onChange={(event) => setServerUrl(event.target.value)} />
          </label>
          <label>
            페어링 코드
            <input value={pairingCode} onChange={(event) => setPairingCode(event.target.value)} inputMode="numeric" />
          </label>
          <div className="button-row">
            <button className="primary-button" disabled={busy}>
              <KeyRound size={16} />
              연결
            </button>
            <button type="button" className="secondary-button" onClick={() => void saveServerUrl()}>
              <Server size={16} />
              URL 저장
            </button>
          </div>
        </form>

        <section className="panel stack">
          <div className="panel-title">
            <ShieldAlert size={18} />
            <h2>실행 조건</h2>
          </div>
          <ul className="check-list">
            <li>카카오톡 PC 앱이 로그인된 상태로 열려 있어야 합니다.</li>
            <li>필수: 손쉬운 사용에서 AutoSend/Electron/터미널/Python 중 표시되는 항목을 허용합니다.</li>
            <li>필수: 자동화 권한 요청이 뜨면 KakaoTalk 제어를 허용합니다.</li>
            <li>선택: 화면 기록은 현재 발송에는 필요 없고 화면 인식 기능을 쓸 때만 필요합니다.</li>
            <li>방 이름이 웹에 입력한 이름과 정확히 같아야 합니다.</li>
          </ul>
          {permissions ? (
            <p className={permissions.ok ? "permission-ok" : "permission-warn"}>
              {permissions.ok ? "필수 권한 준비됨" : permissions.message}
            </p>
          ) : null}
          <div className="button-row">
            <button type="button" className="secondary-button" onClick={() => void refreshPermissions()}>
              <RefreshCw size={16} />
              권한 확인
            </button>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => void requestPermissions(false)}>
              권한 재요청
            </button>
            <button type="button" className="secondary-button" onClick={() => void window.autosend.openPermissionSettings("accessibility")}>
              손쉬운 사용
            </button>
            <button type="button" className="secondary-button" onClick={() => void window.autosend.openPermissionSettings("automation")}>
              자동화
            </button>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => void requestPermissions(true)}>
              화면 기록 요청
            </button>
          </div>
        </section>

        <section className="panel stack">
          <div className="panel-title">
            <RefreshCw size={18} />
            <h2>작업 가져오기</h2>
          </div>
          <p className="muted">
            연결된 상태에서는 12초마다 서버에서 대기 작업을 확인합니다. 작업을 가져와도 최종 확인 전에는 발송하지 않습니다.
          </p>
          <button className="secondary-button" disabled={!connected || busy} onClick={() => void claimNow()}>
            <RefreshCw size={16} />
            지금 확인
          </button>
        </section>
      </section>

      <section className="job-panel">
        <div className="panel-title">
          <Send size={18} />
          <h2>최종 확인</h2>
        </div>
        {pendingJob ? (
          <div className="job-detail">
            <div className="detail-row">
              <span>상태</span>
              <strong>{jobStatusLabels.LOCKED}</strong>
            </div>
            <div className="detail-row">
              <span>수신자</span>
              <strong>{pendingJob.recipientName}</strong>
            </div>
            <div className="detail-row">
              <span>카카오톡 방</span>
              <strong>{pendingJob.kakaoRoomName}</strong>
            </div>
            <div className="message-box">{pendingJob.message}</div>
            {awaitingSendConfirmation ? (
              <div className="confirm-box">
                <p>카카오톡 화면에서 메시지가 실제로 발송되었는지 확인한 뒤 결과를 기록하세요.</p>
                <div className="button-row">
                  <button className="primary-button" disabled={busy} onClick={() => void recordSendResult("SENT")}>
                    <Check size={16} />
                    실제 발송됨
                  </button>
                  <button className="danger-button" disabled={busy} onClick={() => void recordSendResult("FAILED")}>
                    <CircleSlash size={16} />
                    발송 안 됨
                  </button>
                </div>
              </div>
            ) : (
              <div className="button-row">
                <button className="primary-button" disabled={busy} onClick={() => void runCurrentJob()}>
                  <Check size={16} />
                  확인 후 발송
                </button>
                <button className="danger-button" disabled={busy} onClick={() => void rejectJob()}>
                  <CircleSlash size={16} />
                  취소
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="empty-state">확인할 작업이 없습니다.</div>
        )}
        {lastAutomationResult ? (
          <div className="debug-panel">
            <strong>최근 자동화 결과</strong>
            <span>{lastAutomationResult.ok ? "OK" : "FAILED"} / {lastAutomationResult.sent ? "sent" : "not sent"}</span>
            {lastAutomationResult.error ? <span className="debug-error">{lastAutomationResult.error}</span> : null}
            <ol>
              {(lastAutomationResult.steps ?? []).map((step, index) => (
                <li key={`${step}-${index}`}>{step}</li>
              ))}
            </ol>
          </div>
        ) : null}
      </section>
    </main>
  );
}
