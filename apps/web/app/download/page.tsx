import Link from "next/link";
import { ArrowLeft, MonitorDown } from "lucide-react";

export default function DownloadPage() {
  return (
    <main className="workspace narrow">
      <header className="topbar">
        <div>
          <p className="eyebrow">AutoSend</p>
          <h1>PC 앱 다운로드</h1>
        </div>
        <Link href="/dashboard" className="icon-link">
          <ArrowLeft size={18} />
          대시보드
        </Link>
      </header>

      <section className="download-panel">
        <MonitorDown size={40} />
        <div>
          <h2>로컬 빌드 패키지</h2>
          <p>
            데스크톱 앱은 Electron으로 구성되어 있으며 macOS와 Windows 패키징 설정이 포함되어 있습니다. 로컬 개발에서는
            `npm run dev:desktop`, 배포 파일 생성은 `npm run dist -w @autosend/desktop`을 사용합니다.
          </p>
        </div>
      </section>

      <section className="table-panel">
        <h2>빌드 산출물 위치</h2>
        <div className="notion-table simple">
          <div className="table-head table-row">
            <span>OS</span>
            <span>명령</span>
            <span>산출물</span>
          </div>
          <div className="table-row">
            <span>macOS</span>
            <span>npm run dist -w @autosend/desktop</span>
            <span>apps/desktop/release/*.dmg</span>
          </div>
          <div className="table-row">
            <span>Windows</span>
            <span>npm run dist -w @autosend/desktop</span>
            <span>apps/desktop/release/*.exe</span>
          </div>
        </div>
      </section>
    </main>
  );
}

