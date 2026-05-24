# Google Messages 자동화

`google_message.py` 는 macOS / Windows 공통으로 실제 Google Chrome 창을 띄운 뒤
Google Messages Web 에서 다음 단계까지만 자동화합니다.

- [x] Step 1 - `https://messages.google.com/web/conversations` 열기
- [x] Step 2 - `채팅 시작 / Start chat` 클릭
- [x] Step 2 - 전화번호 입력
- [x] Step 3 - `~번으로 보내기` 버튼 클릭
- [x] Step 4 - 메시지 작성 후 전송

## 핵심 방식

Selenium / ChromeDriver / Playwright 를 쓰지 않습니다. Python 표준 라이브러리만으로
Chrome DevTools Protocol(CDP)에 연결해서 **설치된 실제 Chrome** 을 조작합니다.
브라우저는 headless 가 아니며 화면에 그대로 뜹니다.

Google 로그인에서 `브라우저 또는 앱이 안전하지 않을 수 있습니다` 가 뜨는 문제를 피하려고,
스크립트는 WebDriver 브라우저가 아니라 실제 Chrome 프로필을 사용합니다. 다만 Chrome 136
이후에는 보안 정책상 기본 Chrome 프로필에 원격 디버깅을 붙일 수 없으므로, 기본 실행은
전용 Chrome 프로필을 사용합니다.

참고: [Chrome remote debugging security change](https://developer.chrome.com/blog/remote-debugging-port)

## 요구사항

- macOS 또는 Windows
- Python 3.8+
- Google Chrome 설치
- 외부 Python 패키지 없음

`pip install` 이 필요 없습니다. 현재 Python 의 SSL 모듈이 깨져 있어도 localhost CDP
연결만 사용하므로 실행할 수 있습니다.

## 기본 사용법

```bash
python google_message.py "+821012345678" "테스트 메시지입니다."
```

또는 실행 중 입력:

```bash
python google_message.py
```

기본 실행 흐름:

1. 스크립트 폴더의 `.google_messages_chrome_profile` 전용 프로필로 실제 Chrome을 실행합니다.
2. 이미 열린 Google Messages 탭이 있으면 그 탭을 감지하고 페이지 열기 단계를 생략합니다.
3. 열린 탭이 없으면 Google Messages Web 페이지를 엽니다.
4. 처음 실행이면 Chrome 창에서 직접 Google 로그인 또는 Messages 휴대전화 페어링을 완료합니다.
5. `채팅 시작 / Start chat` 버튼이 보이면 자동으로 클릭합니다.
6. 이미 새 대화 화면이면 버튼 클릭도 생략하고 전화번호 입력부터 진행합니다.
7. `~번으로 보내기` 버튼을 클릭하고 메시지 입력창을 확인합니다.
8. 메시지 인자가 있으면 메시지를 입력하고 전송 버튼을 클릭합니다.
9. 메시지 입력창이 비워지면 전송 성공으로 종료합니다.

메시지 인자를 생략하면 Step 3까지만 실행하고 전송하지 않습니다.

## Step 2까지만 실행

전화번호 입력까지만 하고 멈추려면:

```bash
python google_message.py "+821012345678" --fill-only
```

## Step 3까지만 실행

수신자 선택까지만 하고 메시지는 보내지 않으려면 메시지 인자를 생략합니다.

```bash
python google_message.py "+821012345678"
```

## 이미 열린 CDP Chrome에 붙기

직접 Chrome을 디버그 포트로 열어 두고 붙고 싶으면 `--attach-only` 를 사용합니다.

macOS:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="/Users/ijungyu/doing/auto/.google_messages_chrome_profile"

python3 google_message.py "+821012345678" --attach-only
```

Windows PowerShell:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="C:\path\to\auto\.google_messages_chrome_profile"

python google_message.py "+821012345678" --attach-only
```

중요: Chrome 136 이후에는 기본 Chrome 사용자 데이터 폴더에 `--remote-debugging-port` 를
붙이는 방식이 차단될 수 있습니다. 그래서 `--user-data-dir` 은 기본 프로필이 아닌 전용
폴더를 쓰는 것이 안정적입니다.

## 주요 옵션

```bash
python google_message.py "+821012345678" \
  "테스트 메시지입니다." \
  --port 9222 \
  --login-timeout 180 \
  --action-timeout-ms 15000 \
  --debug-dir ./google_message_debug
```

- `--port` - Chrome CDP 포트
- `--attach-only` - 이미 열린 CDP Chrome에만 연결
- `--chrome-executable` - Chrome 실행 파일 경로 직접 지정
- `--message` - positional message 대신 보낼 메시지 지정
- `--user-data-dir` - 전용 Chrome 프로필 경로 지정
- `--profile-directory` - Chrome profile-directory 지정
- `--login-timeout` - 로그인/페어링 및 Start chat 버튼 대기 시간
- `--fill-only` - Step 2까지만 수행하고 `~번으로 보내기` 클릭은 생략
- `--debug-dir` - 실패 시 screenshot/html 저장 위치

## 실패 시 확인

실패하면 `google_message_debug/` 아래에 현재 화면 screenshot 과 HTML 을 저장합니다.
Google Messages 의 버튼명이나 DOM 구조가 바뀐 경우 이 파일로 어느 단계에서 막혔는지
확인할 수 있습니다.

## pip SSL 오류

아래 오류는 스크립트 문제가 아니라 pyenv Python 이 삭제된 OpenSSL 1.1 dylib 를 참조할 때
발생합니다.

```text
ImportError: Library not loaded: /opt/homebrew/opt/openssl@1.1/lib/libssl.1.1.dylib
```

이 스크립트는 외부 패키지가 필요 없으므로 `python google_message.py ...` 로 바로 실행하면 됩니다.
pyenv 자체를 고치려면 Homebrew OpenSSL 버전에 맞춰 Python 을 다시 빌드하는 방식이 필요합니다.

`브라우저 또는 앱이 안전하지 않을 수 있습니다` 가 계속 뜨면:

- Selenium / ChromeDriver 로 열린 브라우저가 아닌지 확인합니다.
- 이 스크립트의 기본 실행처럼 전용 실제 Chrome 프로필에서 직접 로그인/페어링합니다.
- 이미 Chrome이 같은 `--user-data-dir` 로 떠 있으면 모두 닫고 다시 실행합니다.
