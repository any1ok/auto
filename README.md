# AutoSend

로컬 PC에서 실행되는 카카오톡 자동 발송 보조 앱과 Next.js 기반 관리 웹사이트입니다. 웹에서 수신자와 발송 작업을 관리하고, 데스크톱 앱이 사용자의 PC에 열려 있는 카카오톡 화면을 조작해 메시지를 보냅니다.

## 구성

- `apps/web`: Next.js App Router 관리 웹사이트와 API
- `apps/desktop`: Electron 데스크톱 앱
- `apps/automation`: Electron 앱에서 실행하는 Python 카카오톡 UI 자동화
- `packages/shared`: 웹/데스크톱 공통 타입과 상태 라벨

## 로컬 실행

DB는 이미 준비되어 있다고 가정하며 Docker 설정은 포함하지 않습니다.

```bash
npm install
npm run setup:automation
npm run prisma:generate
npm run dev:web
```

웹은 기본적으로 `http://localhost:3000`에서 실행됩니다. 데스크톱 앱 개발 실행은 별도 터미널에서 실행합니다.

```bash
npm run dev:desktop
```

Electron 실행 중 `Error: Electron uninstall`이 나오면 Electron npm 패키지는 있으나 실제 바이너리 다운로드가 빠진 상태입니다. 아래 명령으로 바이너리를 다시 받습니다.

```bash
node -e "console.log(require('electron'))"
npm run dev:desktop
```

그래도 실패하면 의존성을 다시 설치합니다.

```bash
npm install
node -e "console.log(require('electron'))"
npm run dev:desktop
```

`apps/web/.env`에는 다음 값이 들어갑니다.

```bash
DATABASE_URL="postgresql://autosend:7565@localhost:5432/autosend"
SESSION_SECRET="local-development-secret-change-before-production"
NEXT_PUBLIC_APP_NAME="AutoSend"
```

## 사용 흐름

1. 웹에서 회원가입 또는 로그인합니다.
2. `기기` 영역에서 페어링 코드를 생성합니다.
3. 데스크톱 앱에서 서버 URL과 페어링 코드를 입력해 연결합니다.
4. 웹에서 수신자와 발송 작업을 생성합니다.
5. 데스크톱 앱이 작업을 가져오면 사용자가 최종 확인을 누릅니다.
6. Python 자동화가 현재 열려 있는 PC 카카오톡을 조작해 메시지를 전송합니다.
7. 성공/실패 결과는 웹의 발송 작업 표와 로그에 반영됩니다.

## 카카오톡 자동화 전제

- 카카오톡 PC 앱은 사용자가 직접 설치, 로그인, 실행해 둡니다.
- 웹의 `카카오톡 방 이름`은 실제 방 이름과 정확히 일치해야 합니다.
- 이 프로젝트는 카카오톡 공식 API가 아니라 사용자의 로컬 화면을 조작하는 보조 도구입니다.
- 발송 책임, 수신 동의, 서비스 약관 준수는 사용자에게 있습니다.
- 실제 발송 전에는 데스크톱 앱에서 사용자의 최종 확인이 필요합니다.

## OS 권한

macOS에서는 현재 구현 기준으로 아래 권한을 확인합니다.

- 필수: 시스템 설정 > 개인정보 보호 및 보안 > 손쉬운 사용
  - 개발 실행 시 `Terminal` 또는 `iTerm`, `Electron`, `Python` 중 목록에 표시되는 항목을 허용합니다.
  - 패키징 앱 실행 시 `AutoSend`를 허용합니다.
  - 이 권한이 없으면 키 입력, 붙여넣기, Enter 전송이 실제 카카오톡에 전달되지 않을 수 있습니다.
- 필수: 시스템 설정 > 개인정보 보호 및 보안 > 자동화
  - macOS가 `AutoSend`, `Electron`, 또는 터미널이 `KakaoTalk`을 제어하려 한다고 묻는 경우 허용합니다.
  - 이 권한은 카카오톡 창을 앞으로 가져오는 AppleScript에 필요합니다.
- 선택: 시스템 설정 > 개인정보 보호 및 보안 > 화면 기록
  - 현재 발송 흐름은 화면 캡처를 사용하지 않으므로 필수는 아닙니다.
  - 향후 화면 인식, 스크린샷 로그, 이미지 매칭 기능을 켤 때만 필요합니다.

필요하지 않은 권한:

- 입력 모니터링: 키보드 입력을 읽지 않으므로 필요하지 않습니다.
- 전체 디스크 접근: 파일 시스템 전체를 읽지 않으므로 필요하지 않습니다.

Windows에서는 카카오톡 창이 열려 있고 잠금 화면이나 관리자 권한 경계에 막혀 있지 않아야 합니다.

## Python 자동화

개발 환경에서는 자동화 전용 Python venv를 먼저 준비합니다.

```bash
npm run setup:automation
```

권한 상태만 확인하려면 다음 명령을 실행합니다.

```bash
apps/automation/.venv/bin/python apps/automation/autosend_automation.py --check-permissions
```

권한 요청을 다시 띄우려면 다음 명령을 실행하거나 데스크톱 앱의 `권한 재요청` 버튼을 누릅니다.

```bash
apps/automation/.venv/bin/python apps/automation/autosend_automation.py --request-permissions
```

선택 권한인 화면 기록까지 요청하려면 다음 명령을 사용합니다.

```bash
apps/automation/.venv/bin/python apps/automation/autosend_automation.py --request-permissions --request-screen-recording
```

현재 설정에서는 `--dry-run` 플래그가 있어도 채팅방 검색, 메시지 입력, 전송까지 진행합니다. 이 플래그는 기존 개발 명령과의 호환을 위해 남겨두었고, 실제 전송 차단 용도로 사용하지 않습니다.

```bash
apps/automation/.venv/bin/python apps/automation/autosend_automation.py --room "테스트방" --message "테스트 메시지" --dry-run
```

패키징용 바이너리는 PyInstaller로 생성할 수 있습니다.

```bash
python3 -m pip install -r apps/automation/requirements.txt
python3 -m PyInstaller --onefile --name autosend_automation apps/automation/autosend_automation.py
```

생성된 바이너리를 `apps/automation/dist`에 두면 Electron 패키징 시 리소스로 포함되도록 설정되어 있습니다.

## 검증

```bash
npm run lint
npm run typecheck
npm run test
```

실제 카카오톡 전송은 자동 테스트 대신 수동 체크리스트로 확인합니다.

1. 카카오톡 PC 앱을 실행하고 테스트 채팅방을 엽니다.
2. 웹에서 테스트 수신자와 발송 작업을 생성합니다.
3. 데스크톱 앱에서 작업을 가져온 뒤 `확인 후 발송`을 누릅니다.
4. 방 검색, 메시지 입력, 전송이 올바른지 확인합니다.
5. 데스크톱 앱에서 실제 발송 여부를 성공/실패로 기록합니다.

## 구현상 가정

- PostgreSQL은 `postgresql://autosend:7565@localhost:5432/autosend`로 접근 가능합니다.
- 기존 DB의 `User`, `Device`, `Recipient`, `MessageJob`, `SendLog` 테이블과 enum을 재사용합니다.
- 재시도는 자동으로 무한 반복하지 않고, 웹에서 실패 작업을 다시 큐잉하는 방식으로 시작합니다.
- 일반 사용자는 빌드된 데스크톱 앱만 실행하며 Python, Node.js, 개발자 도구를 직접 설치하지 않는 배포를 목표로 합니다.
