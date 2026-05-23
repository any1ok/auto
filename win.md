# 카카오톡 자동화 (Windows)

Python 으로 카카오톡 데스크톱 앱을 단계별로 자동화합니다.
**현재는 Windows 전용** (macOS 는 `mac.md` / `kakao_mac.py` 참고).

## 스텝

- [x] Step 1 — 이미 실행 중인 카카오톡 메인 창을 foreground 로
- [x] Step 2 — 친구(1) / 채팅(2) / 더보기(3) 탭 포커스 (Ctrl+Tab 으로 도달까지 반복)
- [x] Step 3 — 현재 탭 상단 검색창에 텍스트 입력 (Enter 미입력)
- [x] Step 4/5/6 — 검색 결과를 ↓/Enter 로 위에서부터 하나씩 열어 채팅창 타이틀로
  매칭 검증 (통합 구현). 불일치면 ESC 로 즉시 닫고 다음 결과 시도, 매치면 창
  그대로 두고 성공. mac.md 처럼 결과 리스트 텍스트를 직접 읽지 않고 **열린
  채팅창의 top-level 윈도우 타이틀** 만으로 검증.
- [x] Step 7 — 열린 채팅방의 RichEdit 입력란에 메시지를 **클립보드 + Ctrl+V
  (SendInput)** 로 paste 한 뒤 **VK_RETURN (SendInput)** 으로 전송. 전송 검증
  = RichEdit 내용이 보낸 메시지에서 다른 내용으로 바뀌었는지 폴링 (보통 비거나
  placeholder '메시지 입력' 으로 토글되므로 length 기반 검증은 placeholder
  때문에 오작동, 반드시 내용 비교).

> 각 step 의 의미는 `mac.md` 와 동일합니다. 단, 구현은 macOS 의 `osascript` /
> AppleScript / `pbcopy` 가 아니라 **Win32 API (user32 / kernel32) 를 ctypes
> 로 직접 호출**하는 식으로 윈도우 사정에 맞춰 다시 작성합니다.

## 요구사항

- Windows 10 이상, Python 3.8+
- 카카오톡 데스크톱 앱을 미리 실행 (트레이로 숨기지 않고 메인 창이 떠 있는 상태 권장)
- 외부 라이브러리 없음 (`ctypes` 만 사용)

## 사용법

```bat
:: 대화형 — 탭(1/2/3) / 검색어 / (선택) 메시지를 차례로 물어 step 1 → 7 실행
python kakao_win.py

:: 탭 + 검색어만 — Step 4/5/6 까지 (채팅방만 열고 끝)
python kakao_win.py 1 "홍길동"
python kakao_win.py 2 "회사"
python kakao_win.py 3 "오픈채팅"

:: 탭 + 검색어 + 메시지 — Step 7 까지 (전송까지)
python kakao_win.py 2 "홍길동" "안녕하세요"

:: 탭만 인자로 주고 검색어 / 메시지는 input() 으로 받기 (메시지 빈 입력 = 생략)
python kakao_win.py 2
```

성공 시 출력 (EXACT 매치 — 첫 시도에서 바로 맞은 경우, Step 7 까지):

```
[Step 1] 카카오톡을 포커스했습니다.
[Step 2] 채팅 탭으로 포커스했습니다. (Ctrl+Tab × 1)
[Step 3] 검색창에 입력 완료: '홍길동'
[Step 4/5/6] '홍길동' EXACT 매치 — title='홍길동' (시도 1/10, 채팅 탭). 채팅방 열림 확인.
[Step 7] 메시지 전송 완료 (chat hwnd=0x..., msg_edit=0x..., class='RichEdit50W', 길이=N → 0).
```

검색 결과의 윗쪽 몇 개가 다른 방이면 stderr 로 각 시도별 진단(시도 N, 새 hwnd,
열린 title) 이 찍히고, ESC 로 자동으로 닫으면서 ↓ 로 다음 결과로 넘어갑니다.

이미 목표 탭이 활성 상태였다면 Step 2 가 `(이미 활성 탭, Ctrl+Tab × 0)` 으로 끝납니다.

종료 코드:

- `0` 성공
- `1` `KakaoWinError` (카카오톡이 안 떠 있음 / 메인 창을 못 찾음 / foreground 전환 실패 / 탭 패널 못 찾음 / 탭 전환 도달 실패 / 검색창 컨트롤 못 찾음 / WM_SETTEXT 실패 / Enter 후 채팅창이 안 뜸 / 결과 리스트에 매치되는 항목 없음 / PostMessage 실패 / 메시지 입력 RichEdit 못 찾음 / 메시지 전송 검증 실패 등)
- `2` 잘못된 인자 (`1|2|3` 외의 값, 인자가 4 개 이상, 빈 검색어 인자)

## 권한

- macOS 의 손쉬운 사용(Accessibility) 같은 별도 권한은 보통 필요 없습니다.
- 단 **카카오톡이 관리자(Run as administrator) 권한으로 실행 중**이라면
  스크립트도 같은 권한으로 실행해야 합니다. Windows 의 UIPI(User Interface
  Privilege Isolation) 때문에 낮은 권한 프로세스가 높은 권한 윈도우를
  포커스 / 조작할 수 없습니다. 한쪽만 관리자 권한이면 Step 1 의 `SetForegroundWindow`
  자체가 무시되거나 타임아웃에서 실패합니다.

## 설계 노트 (실패 회피용)

- 프로세스 탐색에 `tasklist` 를 쓰지 않음. `tasklist` 출력은 한글 OS 에서
  cp949(MBCS) 라 Python 의 기본 utf-8 로 읽으면 깨질 수 있고, 헤더/포맷도
  로케일 마다 다름. 대신 **`CreateToolhelp32Snapshot` + `Process32FirstW/NextW`**
  로 직접 enumerate. (유니코드 W API 라 한글/영문 환경 모두 안전.)
- "메인 창" 후보는 `EnumWindows` 로 모든 top-level 창을 훑으면서
  **`GetWindowThreadProcessId` + `QueryFullProcessImageNameW`** 로 소유
  프로세스가 `KakaoTalk.exe` 인지 확인. 그중 타이틀이 정확히 `"카카오톡"` 또는
  `"KakaoTalk"` 인 visible 창을 1순위로, 점차 hidden / 타이틀만 있는 창을
  fallback 으로 점수화 (`_pick_main_window`).
- `EnumWindows` 콜백은 반드시 `WINFUNCTYPE` (stdcall). `CFUNCTYPE` (cdecl) 로
  쓰면 호출 규약이 맞지 않아 스택이 어긋남. 그리고 콜백 객체는 변수에 저장해
  EnumWindows 호출 끝날 때까지 GC 되지 않게 유지.
- `OpenProcess` 권한은 `PROCESS_QUERY_LIMITED_INFORMATION` (0x1000) 만 요청.
  `PROCESS_QUERY_INFORMATION` 은 일부 보호 프로세스에서 막히므로, 더 약한
  권한으로 충분한 `QueryFullProcessImageNameW` 만 사용 (Vista+).
- 카카오톡이 최소화 / 트레이로 내려간 상태면 먼저 `ShowWindow(hwnd, SW_RESTORE)`
  로 복원한 뒤 foreground 시도. (트레이에서 메인 창이 완전히 destroy 된 상태는
  Step 1 범위 밖 — 별도 step 으로 분리 예정.)
- `SetForegroundWindow` 는 [포커스 절도 방지](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)
  때문에 임의 프로세스가 호출하면 그냥 무시되는 경우가 많다. 우회를 위해
  **현재 foreground 창의 스레드와 우리 스레드, 그리고 타겟 창의 스레드를
  `AttachThreadInput` 으로 같은 입력 큐에 묶은 다음** `BringWindowToTop` +
  `SetForegroundWindow` 호출, 끝나면 detach. macOS 의 `tell application
  "KakaoTalk" to activate` 와 같은 효과를 안정적으로 얻기 위한 표준 트릭.
- activate 직후 무조건 `sleep` 하지 않음. `mac.md` 의 frontmost 폴링과 같은
  방식으로 **`GetForegroundWindow()` 가 우리 hwnd 와 같아질 때까지 40 ms 간격,
  1.5 s 타임아웃 폴링**.
- 진단 가독성: 메인 창 후보가 없으면 KakaoTalk.exe 가 소유한 top-level 창
  목록 (hwnd / title / visible / iconic) 을 stderr 에 같이 찍어, 트레이만
  떠 있는 상태인지 / 타이틀이 예상 외인지 바로 알 수 있게 한다.

### Step 2 — 탭 포커스 (친구 / 채팅 / 더보기)

- 카카오톡 PC 는 **mac 의 `⌘+1` / `⌘+2` 같은 절대 위치 단축키가 없다.**
  공식 단축키는 [`Ctrl+Tab` (탭 이동)](https://cs.kakao.com/helps_html/1073183088?locale=en)
  뿐이라 무조건 1회 보내면 같은 탭 재선택 시 다른 탭으로 가버린다. 반드시
  **현재 활성 탭을 감지해 목표 탭이 될 때까지 반복** 으로 의미상 동등성 확보.
- 탭 감지는 **메인 `#32770` → `EVA_ChildWindow` → 직속 자식 `EVA_Window` 들**
  중 `IsWindowVisible == true` 인 것의 0-indexed 위치로 한다. 카톡 PC 는
  탭 전환 시 패널 EVA_Window 하나만 visible 로 토글한다 ([Spy++ 분석](https://ssam2s.tistory.com/9)).
  매핑: idx 0 = 친구, idx 1 = 채팅, idx 2 = 더보기 (사이드바 위→아래 순서).
- `EnumChildWindows` 는 **손자까지 재귀 enumerate** 한다. 직속 자식만 원하면
  콜백에서 `GetParent(child) == parent` 로 필터링 필수.
- `FindWindowExW` 의 클래스명 인자는 wide string — `"EVA_ChildWindow"`,
  `"EVA_Window"` 정확히. 카톡 빌드 변경으로 클래스명이 바뀌면 못 찾으므로,
  이 경우 메인창 직속 자식 클래스 목록을 stderr 에 덤프해 즉시 진단 가능
  하게 한다 (Step 1 의 trayed-only 진단 출력과 같은 패턴).
- 키 입력은 `PostMessage(WM_KEYDOWN, VK_CONTROL/VK_TAB)` 을 쓰지 않는다.
  비활성 윈도우에 보낼 수는 있지만 시스템 modifier state 가 갱신되지 않아
  카톡이 "그냥 Tab" 으로만 인식하는 사례가 흔하다. 대신 **`SendInput`** 으로
  `VK_CONTROL down → VK_TAB down → VK_TAB up → VK_CONTROL up` 4 개를
  한 batch 로 전송 (Step 1 에서 카톡을 foreground 로 만들어 둔 전제).
- `SendInput` 의 `cbSize` 는 반드시 `ctypes.sizeof(_INPUT)`. 32-bit 는 28,
  64-bit 는 40 으로 다르고 잘못 주면 `0` 만 반환하며 silent 실패. `INPUT` 의
  union 안에 `MOUSEINPUT` 까지 전부 정의해서 union 전체 sizeof 가 INPUT
  sizeof 에 정확히 반영되도록 `ctypes.Union` 으로 묶는다 ([stackoverflow](https://stackoverflow.com/questions/62189991/how-to-wrap-the-sendinput-function-to-python-using-ctypes)).
- `KEYBDINPUT.wScan` 도 `MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)` 결과로 채운다.
  일부 앱은 `wVk` 만 채우고 보내면 무시한다 (KEYEVENTF_SCANCODE 플래그
  까지는 안 써도 됨).
- `Ctrl+Tab` 직후 패널 visible 상태 갱신에 약간 지연이 있어, 80 ms 짧은
  sleep 후 60 ms 간격으로 visible idx 가 직전 값과 달라질 때까지 짧게
  폴링한다. 안 달라지면 다음 press 로 넘어간다.
- 무한 루프 방지: 최대 **8 회** Ctrl+Tab 안에 도달 못 하면 진단 (시도 횟수
  / 마지막 visible idx / 패널 hwnd 목록) 과 함께 에러. 일반적으로 사이클
  길이(3) 안에서 도달한다.
- Step 1 ~ Step 2 사이에 사용자가 다른 창을 클릭했을 수 있어, step 2 진입
  시 **`_force_foreground` + `wait_for_foreground` 를 한 번 더 호출** 한다.
  mac.py 가 매 step 마다 `_activate_kakao()` 부르는 것과 같은 이유.
  `AttachThreadInput` 트릭은 Step 1 에서 이미 카톡이 foreground 이므로
  Step 2 에서는 불필요.
- 모든 `input()` 은 Step 1 이전에. 단계 중간에 input 받으면 터미널로
  포커스가 빠져 키 입력이 새는다 (mac.md 와 동일한 노트).
- `Ctrl+Tab` 은 modifier + Tab 조합이라 **한글 IME 영향을 받지 않는다**
  (mac.md 의 "f → ㄹ" 같은 IME 번역 이슈와 무관).

### Step 3 — 검색창에 텍스트 입력

- 검색창은 카톡 자체 컨트롤이 아니라 **표준 Win32 `Edit`** 이다 ([Spy++ 분석](https://ssam2s.tistory.com/9), [slaner](https://slaner.tistory.com/150)). 그래서 `SendMessageW(edit, WM_SETTEXT, 0, text)`
  로 한글 그대로 set 가능. mac.md 의 `pbcopy + ⌘V` 는 한글 IME 가
  `keystroke "f"` → "ㄹ" 로 번역하는 이슈 회피용인데, Win32 `Edit` 의
  W 메시지는 wide-char 라 IME 와 무관하다. **클립보드 조작 / 키 입력
  시뮬레이션이 필요 없다**.
- 검색 결과 갱신은 `Edit` 컨트롤이 자동 발송하는 `EN_CHANGE` 통지로
  카톡이 트리거. 별도 키 이벤트 (Tab / 엔터 등) 안 보내도 됨. Step 5 가
  실제 Return 을 보낼 때까지 검색창에 글자만 들어가 있는 상태.
- **현재 visible 인 EVA_Window 패널의 직속 자식 Edit 만** 사용. 비활성
  탭의 EVA_Window 패널 안에도 같은 클래스의 Edit 이 살아 있어, 패널을
  안 가리고 잡으면 보이지 않는 탭의 검색창에 글자가 들어가는 사고가 난다.
  Step 2 가 보장한 visible idx 를 한 번 더 검사해 일치할 때만 진행.
- `EnumChildWindows` 는 손자까지 재귀하니 Step 2 와 같이 `GetParent ==
  panel` 로 직속만 필터해 Edit 을 찾는다.
- `SendMessageW` 의 `lParam` 은 `LPCWSTR` 포인터. ctypes 에서 argtypes 가
  `LPARAM` (정수) 라 `ctypes.cast` 로는 변환이 안 된다. `ctypes.create_unicode_buffer(query)`
  로 wide 버퍼를 만든 뒤 `ctypes.addressof(buf)` 정수 주소를 lParam 으로
  넘기고, **버퍼 객체는 호출 동안 변수에 잡아둬 GC 되지 않게 한다**.
- `LRESULT` 는 `ctypes.wintypes` 에 없어서 `c_ssize_t` 로 직접 지정 (포인터
  폭과 같음 — 32/64 bit 자동 대응).
- `WM_SETTEXT` 의 반환값은 `1` = 성공 / `0` = 실패. `0` 이면 `GetLastError`
  와 함께 진단 메시지에 **UIPI** (카톡이 관리자 권한 / 스크립트는 일반
  권한이라 메시지가 차단됨) 가능성을 같이 출력한다. Step 1 의 권한 노트와
  같은 원인.
- 빌드 변경으로 검색창 클래스명이 `Edit` 가 아닌 다른 이름이 되면 못 찾는다.
  이 경우 visible 패널의 직속 자식 hwnd / class 목록을 stderr 에 덤프해
  Step 1/2 의 진단 출력 패턴을 그대로 따른다.
- Step 2 ~ Step 3 사이에 사용자가 다른 창을 클릭했을 가능성이 있어, Step 3
  진입 시 `_force_foreground` + `wait_for_foreground` 를 한 번 더 호출.
  mac.py 가 매 step 마다 activate 부르는 것과 같은 패턴.

### Step 4/5/6 — 검색 결과 열기 + 타이틀 검증 (통합)

- 카카오톡 PC 의 결과 리스트는 EVA 커스텀 컨트롤이라 표준 Win32 메시지로
  텍스트를 직접 뽑기 까다롭다. mac 의 `AXOutline > AXRow` 같은 접근 가능한
  접근성 트리도 없다. 대신 카톡 PC 의 검증된 동작 — **검색 `Edit` 핸들에
  Enter 만 보내면 현재 하이라이트된(=첫) 결과가 새 채팅창 윈도우로 자동
  오픈** ([ssam2s.tistory.com/9](https://ssam2s.tistory.com/9),
  [airfox1.tistory.com/5](https://airfox1.tistory.com/5)) — 을 활용해, 결과를
  한 칸씩 열고 **열린 채팅창의 top-level 윈도우 타이틀** 로 매칭을 검증한다.
  ("리스트를 읽는다" 가 아니라 "열어 본다" 패턴.)
- 알고리즘: 시도 = `Enter` → 새 top-level 카톡 윈도우 폴링 → 타이틀 확인 →
  매치면 종료, 불일치면 `ESC` 로 즉시 닫고 `↓` 로 하이라이트 한 칸 이동.
  사용자가 알아채기 전에 빠져나오기 위해 새 윈도우 폴링 1.5 s / 닫힘 폴링
  0.5 s 로 짧게.
- **Phase 0 (early-exit)**: 시도 시작 전에 이미 query 와 매치하는 채팅창이
  떠 있으면 (= 이전 호출/유저 조작으로 미리 열려 있음) Enter loop 를 통째로
  생략. 이미 열려 있는 방을 굳이 다시 열어 깜빡이게 만들지 않는다.
- WM_SETTEXT 직후 검색 결과 리스트 갱신 대기: `OPEN_VERIFY_INITIAL_DELAY_S =
  1.0 s`. [airfox1.tistory.com/5](https://airfox1.tistory.com/5) 의 검증된
  예제도 WM_SETTEXT 후 `time.sleep(1)` 을 안정성용으로 명시. 채팅 탭은
  메시지 본문까지 인덱스 검색이라 친구 탭보다 느린 경우가 있다.
- 매칭 우선순위는 mac 의 Step 6 과 같은 패턴 — `title == query` (EXACT) 가
  뜨면 강한 확정, `query in title` (CONTAINS) 만 되면 약한 확정(타이틀
  장식 가능성), 그 외는 불일치.
- 키 입력은 `PostMessage(WM_KEYDOWN/UP)` 로 검색 `Edit` / 검색결과 리스트
  컨트롤 / 채팅창 hwnd 에 직접 전송. Step 2 의 "PostMessage 금지" 노트는
  `Ctrl+Tab` 같은 **modifier+key 의 시스템 키보드 상태 갱신 이슈** 때문인데,
  여기서 쓰는 `VK_RETURN` / `VK_DOWN` / `VK_ESCAPE` 는 modifier 가 없어
  PostMessage 만으로 충분하다 (ssam2s/airfox1 의 검증된 패턴, `lParam=0`
  으로도 동작).
- **VK_DOWN 의 타겟은 Edit 이 아니라 검색결과 리스트 컨트롤**: 진단 덤프로
  EVA_Window 패널 직속 자식에 `EVA_VH_ListControl_Dblclk` 가 두 개 있는 게
  확인됐다 (title `ChatRoomListCtrl_*` = 평소 채팅/친구 목록 visible=False,
  `SearchListCtrl_*` = 검색 결과 visible=True). `↓` 를 Edit 에 PostMessage
  하면 single-line Edit 이 `↓` 를 자체 처리(=무시) 해 검색결과 하이라이트가
  안 움직인다. **`SearchListCtrl_*` hwnd 에 직접 PostMessage 하면** 리스트
  컨트롤이 받아 다음 row 로 하이라이트를 옮겨, 후속 Enter 가 그 row 를 연다.
  Enter 는 그대로 Edit 에 보낸다 (Edit 이 부모로 forward 해 잘 동작).
- 리스트 컨트롤 검색은 `_find_search_list_ctrl(panel_hwnd)`: 패널 직속 자식
  중 `EVA_VH_ListControl_Dblclk` 이고 visible 한 hwnd 를 후보로 모은 뒤,
  title 이 `SearchListCtrl` 로 시작하는 것을 1순위로 잡는다. 검색 중에는
  SearchListCtrl 만 visible 이라 1순위가 정상적으로 결정된다. 친구 탭처럼
  SearchListCtrl 자체가 안 잡히는 케이스 (이미 매치된 첫 결과로 끝남) 에는
  fallback 으로 Edit 에 ↓ 를 보낸다 (해당 케이스는 어차피 ↓ 자체가 필요 없음).
- `ESC` 는 [카카오 공식 단축키 표](https://cs.kakao.com/helps_html/1073183088?locale=ko)
  의 "Close chatroom" 으로 문서화되어 있어, 임의로 띄운 채팅창을 가장
  안전하게 닫는 키다. `WM_CLOSE` 도 가능하지만 카톡 빌드에 따라 "나가시겠
  습니까?" 확인 다이얼로그를 띄울 위험이 있어 회피한다.
- "새 채팅창" 판정은 시도 직전 `_enum_kakao_windows()` 로 hwnd 집합
  `baseline` 을 스냅샷한 뒤, 시도 후 늘어난 hwnd + 비어있지 않은 title 을
  잡는 방식. 매 시도마다 baseline 을 갱신해 (ESC 가 실패해 안 닫힌 경우
  포함) 이전 hwnd 가 다음 판정에 섞이지 않게 한다.
- 무한 시도 방지 1 — `OPEN_MAX_ATTEMPTS = 10`. 보통 위쪽 1 ~ 3 개 안에
  매치되거나 결과 자체가 비어 있다.
- 무한 시도 방지 2 — **`SAME_TITLE_BOTTOM_RUN = 3` 회 연속 같은 title**.
  `↓` 가 결과 리스트 끝에 도달하면 더 이상 내려가지 않고 같은 방이 다시
  열리므로, 동일 title 이 3 회 연속 나오면 "리스트 끝" 으로 보고 멈춘다.
  (검색 결과가 2 ~ 3 개 뿐인 흔한 케이스를 자연스럽게 종료시키는 장치.)
- 리스트 컨트롤 클래스명이 카톡 빌드 변경으로 바뀌어 SearchListCtrl 을 못
  잡으면 `SAME_TITLE_BOTTOM_RUN` 이 첫 시도 직후 3 회 만에 발동하므로 stderr
  진단으로 즉시 식별 가능. 그 경우 `KAKAO_LIST_CTRL_CLASS` /
  `KAKAO_SEARCH_LIST_TITLE_PREFIX` 상수를 새 클래스/접두사에 맞춰 교체하면
  된다. 추가 fallback 으로 `VK_DOWN` 대신 `VK_NEXT` (=Page Down — Friend/Chat
  List 공식 단축키 "리스트 위/아래 이동") 를 SearchListCtrl 에 보내는 방법도 있다.
- `Enter` 후에도 새 윈도우가 안 뜨는 경우의 진단: stderr 에 현재 모든
  KakaoTalk top-level 윈도우 (hwnd / title / visible / iconic / baseline
  여부) 를 덤프해, 인라인 패널 모드(별도 윈도우 대신 메인창 안에서 채팅
  방을 보여주는 옵션) 일 가능성 / 검색 결과가 비었을 가능성을 즉시 구별
  할 수 있게 한다.
- Step 3 ~ Step 4/5/6 사이에 사용자가 다른 창을 클릭했을 가능성이 있어,
  Step 4/5/6 진입 시에도 `_force_foreground` + `wait_for_foreground` 를
  한 번 더 호출 (Step 2/3 진입 시와 같은 패턴).

### Step 7 — 메시지 입력 + 전송

- 카톡 PC 의 메시지 입력란은 표준 Win32 `Edit` 가 아니라 **`RichEdit` 컨트롤**.
  클래스명은 카톡 빌드 / RichEdit DLL 버전에 따라 다르고 다수 독립
  레퍼런스가 서로 다른 이름을 기록한다 — `RichEdit50W` (최근, 2020+ ;
  [ssam2s.tistory.com/9](https://ssam2s.tistory.com/9),
  [Xenia101/KakaoTalk-python](https://github.com/Xenia101/KakaoTalk-python/blob/master/app.py))
  / `RichEdit20W` (구버전 ;
  [airfox1.tistory.com/5](https://airfox1.tistory.com/5),
  [oppadu.com 엑셀 카카오톡 자동화](https://www.oppadu.com/%EC%97%91%EC%85%80-%EC%B9%B4%EC%B9%B4%EC%98%A4%ED%86%A1-%EC%9E%90%EB%8F%99%ED%99%94-%EC%98%88%EC%A0%9C/)).
  후보를 순서대로 시도 (`KAKAO_MSG_EDIT_CLASSES`), 둘 다 못 찾으면
  `EnumChildWindows` 로 재귀 enumerate 해서 `RichEdit` 접두사 후손을 fallback.
  Step 2/3 의 직속 자식 패턴 (`_enum_direct_children`) 과 달리 손자까지
  훑는 `_enum_all_descendants` 를 쓴다 — 빌드에 따라 채팅창이 RichEdit 을
  중간 컨테이너 한 번 감쌀 수 있음.

#### 옛 표준 패턴이 최근 빌드에서 안 통하는 이유

- 다수 독립 레퍼런스 (airfox1 2020 / ssam2s 2023 / Xenia101 / 오빠두 VBA) 의
  옛 절차:
  ```
  SendMessage(edit, WM_SETTEXT, 0, text)        # 텍스트 set
  PostMessage(edit, WM_KEYDOWN, VK_RETURN, 0)
  PostMessage(edit, WM_KEYUP,   VK_RETURN, 0)
  ```
  **최근 카카오톡 빌드에서는 이 패턴 전체가 무시된다.** 실측 진단으로 다음을
  하나씩 시도해서 전부 실패 확인:
  - `PostMessage WM_KEYDOWN/WM_KEYUP VK_RETURN`
  - `SendMessage WM_KEYDOWN/WM_KEYUP VK_RETURN` (sync)
  - `_force_focus(msg_edit) + SendInput VK_RETURN`
  - `AttachThreadInput + SetFocus + SendInput VK_RETURN` (attach 유지 상태)
  - `SendMessage WM_CHAR 0x0D` (carriage return char 직접 주입)
  - `Attach + SetFocus + SetKeyboardState(VK_RETURN=0x80) + PostMessage trio`
    (WM_KEYDOWN + WM_CHAR 0x0D + WM_KEYUP, proper lParam scan code 포함)

  유일하게 동작한 패턴: **클립보드 set → SendInput Ctrl+V → SendInput Enter**.

- 가설: 최근 카톡 RichEdit subclass 는 "이 텍스트는 사용자가 input pipeline
  으로 직접 친 거다" 라는 internal flag 가 있어야 Enter 를 send trigger 로
  인식한다. `WM_SETTEXT` 로 직접 set 한 텍스트는 그 flag 가 없어 어떤 방식
  으로 Enter 를 보내도 무시된다. `Ctrl+V (WM_PASTE)` 로 들어간 텍스트는
  flag 가 set 되어 Enter 가 send trigger 가 된다. (Microsoft 공식 답
  [devblogs.microsoft.com/oldnewthing 2025-03-19 "You can't simulate keyboard
  input with PostMessage, revisited"](https://devblogs.microsoft.com/oldnewthing/20250319-00/?p=110979)
  의 일반 원리와도 일치 — input queue 를 거치지 않은 메시지는 subclass /
  hook 검증에서 걸린다. PostMessage 는 posted message queue 에서 바로
  dispatch 되어 input queue 와 `WH_KEYBOARD` hook 을 건너뛴다.)

- 동일한 현상이 IME 영역에서도 보고됨 — rayshoo/kolemak (TSF 기반 한글 IME)
  의 카톡 호환 패치
  [ff420a8](https://github.com/rayshoo/kolemak/commit/ff420a89c7108828b181ed358110e6a4c40c74a9)
  도 카톡에는 SendInput 으로 Enter 재주입 해야 동작한다고 명시. PostMessage
  / SendMessage 만으로 trigger 되는 시기는 지났다.

- 또 다른 참고: [choi97201.tistory.com/27](https://choi97201.tistory.com/27)
  은 `pyautogui.hotkey('ctrl', 'v')` + `pyautogui.press('enter')` 패턴을
  카톡 전송에 쓴다. PyAutoGUI 의 내부 구현이 SendInput 이라, 우리가 ctypes
  로 직접 구현한 절차와 동등하다.

#### 우리 구현 절차

1. `_find_message_edit(chat_hwnd)` — RichEdit 입력란 hwnd 찾기.
2. `_force_foreground(chat_hwnd)` + `wait_for_foreground` (Step 4/5/6 직후
   사용자가 다른 창을 클릭했을 수 있으므로). 채팅창은 top-level 윈도우라
   메인창 활성화 트릭이 그대로 통한다.
3. `_force_focus(msg_edit)` — cross-thread `SetFocus`. `AttachThreadInput`
   으로 입력 큐를 묶은 뒤 SetFocus → GetFocus 검증 → Detach 의 표준 트릭.
   SendInput 은 foreground 윈도우의 focused 컨트롤로 들어가므로 msg_edit
   이 정확히 포커스를 잡고 있어야 Ctrl+V / Enter 가 다른 컨트롤로 안 샌다.
   카톡 채팅창의 default focus 가 message edit 이라 실패해도 대부분 자연
   스레 잡힘 → 경고만 찍고 진행하고 검증 단계에서 결과 확정.
4. 사전에 `_clipboard_get_unicode()` 로 원본 클립보드 저장 (best-effort).
5. `_clipboard_set_unicode(message)` — `GlobalAlloc(GMEM_MOVEABLE)` +
   `GlobalLock` + `memmove(wchar buffer)` + `OpenClipboard` +
   `EmptyClipboard` + `SetClipboardData(CF_UNICODETEXT, hmem)` +
   `CloseClipboard` 의 Win32 표준 절차. 한글 / 유니코드는 CF_UNICODETEXT
   (UTF-16) 로 set 하므로 IME / 인코딩 변환 없이 그대로 paste.
   `SetClipboardData` 호출 후 `hmem` ownership 이 클립보드로 넘어가서
   우리가 `GlobalFree` 하면 안 된다.
6. `_send_ctrl_v()` — SendInput batch 로 `VK_CONTROL down → V down → V up
   → VK_CONTROL up` 한 번 전송. KEYBDINPUT 의 wScan 까지 MapVirtualKeyW
   로 채워 둠 (Step 2 와 같은 이유).
7. `_wait_text_equals(msg_edit, message, 1.0s)` — RichEdit 의 텍스트가
   우리 메시지로 채워졌는지 폴링. paste 도달 확인.
8. `_send_vk_sendinput(VK_RETURN)` — SendInput 으로 VK_RETURN KEYDOWN +
   KEYUP. paste 된 텍스트는 user-input flag 가 set 되어 카톡이 send
   trigger 로 인식한다.
9. `_wait_text_changed_from(msg_edit, message, 2.0s)` — RichEdit 텍스트가
   "더 이상 우리 메시지가 아님" 으로 변하길 폴링. **`length == 0` 검증은
   하면 안 된다** — 카톡이 빈 상태에서 placeholder `'메시지 입력'` (6 글자)
   를 표시하므로 length 는 6 이지 0 이 아니다. 반드시 텍스트 내용 비교.
10. `finally` 블록에서 원본 클립보드 복원 (CF_UNICODETEXT 만 best-effort;
    HTML / 이미지 / 파일 같은 다른 형식은 보존 불가).

#### 그 외 노트

- 줄바꿈 `\n` 이 들어 있어도 Ctrl+V paste 한 뒤 Enter 면 카톡이 multi-line
  메시지 그대로 전송 (카톡 PC 의 키 정의: `Shift+Enter` 가 줄바꿈, 그냥
  `Enter` 가 전송). 단 RichEdit 은 paste 받은 LF (`\n`) 만의 텍스트를 내부
  에서 CRLF (`\r\n`) 로 변환해 저장하고 WM_GETTEXT 도 CRLF 로 돌려준다.
  paste 검증 / 전송 검증의 글자 비교는 `_normalize_newlines` 로 양쪽 줄바꿈
  표기를 `\n` 한 가지로 정규화 후 비교해 이 차이를 흡수한다.
- 빈 메시지(`""`) 는 caller 책임으로 사전 거부 — `main` 도 빈 입력이면
  Step 7 자체를 건너뛰고 "(생략)" 출력만.
- `OpenClipboard` 는 한 프로세스만 동시에 잡을 수 있어 짧게 (20 ms × 10 회)
  재시도. 다른 프로세스가 계속 잡고 있으면 진단 에러.
- 클립보드 사용은 사용자가 다른 데서 쓰던 내용을 덮어쓰는 부작용이 있다.
  CF_UNICODETEXT 한정 best-effort 복원이라 HTML / 이미지 / 파일 클립보드는
  지워진다는 한계 있음. 자동화 도중 사용자에게 "복사한 내용 잠시 동안
  바뀝니다" 안내가 필요하면 caller 가 별도로 처리.

#### 회귀 테스트로 잡은 버그들 (모두 fix 완료)

방대한 케이스 (`_test_step7.py` — 34 케이스: 짧은 한글/영문, 매우 긴 1000자
ASCII, 다양한 이모지/ZWJ/한자 기호/한글 자모, 멀티라인, URL, HTML 모양,
공백/탭/제어문자, pre-existing text 오염, 연속 3회 전송, 클립보드 보존)
실측 후 발견된 4 가지 버그와 fix.

- **버그 1 — UTF-16 surrogate pair 잘림 (이모지 → `?`)**
  - 증상: `🎉🚀` 같은 BMP 외 이모지가 paste 후 `??` 로 변형. paste verify 가
    fail 처리하거나 (가운데 잘림 시) 그대로 전송되더라도 수신측에서 `?` 로
    렌더.
  - 원인: `_clipboard_set_unicode` 에서 `(len(text) + 1) * sizeof(c_wchar)` 로
    바이트 크기를 계산했는데, **Python `len()` 은 code point 수 (이모지 = 1)
    지만 UTF-16 / wchar_t 는 surrogate pair 로 2 unit** 을 쓴다. 그래서 buffer
    가 부족하고 `memmove` 가 surrogate pair 의 lower half 를 잘라 unpaired
    surrogate (= invalid UTF-16) 가 됨. 카톡이 invalid surrogate 를 `?` 로
    렌더.
  - Fix: `ctypes.create_unicode_buffer(text)` 가 내부에서 `PyUnicode_AsWideChar`
    로 정확한 wchar 수를 산출하므로, 그 결과 버퍼의 `ctypes.sizeof()` 를
    그대로 byte 수로 사용. supplementary 평면 문자도 안전.

- **버그 2 — RichEdit 의 `\t` → 가변 공백 변환**
  - 증상: `'탭\t문자\t테스트'` paste 후 RichEdit 내용이 `'탭  문자   테스트'`
    (탭 1 → 2 spaces, 탭 2 → 3 spaces, tab stop 정렬). 우리 strict equality
    검증이 fail.
  - 원인: RichEdit 은 paste 받은 `\t` 를 다음 tab stop 까지 가변 길이 공백으로
    확장한다. 일반적인 텍스트 편집기와 같은 의도된 동작이라 막을 수 없다.
  - Fix: `_sanitize_message_for_richedit` 로 caller 가 보낸 메시지의 `\t` 를
    paste 전에 미리 4 spaces 로 치환. 이제 RichEdit 이 변형할 게 없어 paste
    결과 = 우리가 set 한 내용. 같은 함수에서 `\v` / `\f` / NULL 같은 다른
    paste-시 RichEdit 이 손대는 control char 도 함께 정규화.

- **버그 3 — msg_edit 에 pre-existing text 가 있을 때 메시지가 prefix 붙어 전송**
  - 증상: 사용자가 손으로 친 잔여물(예: `' sex'`) 이나 이전 자동화 실패의
    찌꺼기가 msg_edit 에 남아 있으면, Ctrl+V 가 caret 위치에 우리 메시지를
    "삽입" 해 `' sex<우리 메시지>'` 같은 모양이 되고 paste verify 가 fail
    (또는 전송돼도 prefix 오염).
  - 원인: Ctrl+V 는 선택 영역이 없으면 단순 insert. 빈 RichEdit 일 때는
    문제 없지만, 잔여물이 있으면 그 옆에 붙는다.
  - Fix: Ctrl+V **직전에 Ctrl+A** 를 한 번 더 SendInput. RichEdit 의 모든
    텍스트가 선택되고, 이어지는 Ctrl+V 가 선택 영역을 우리 메시지로 치환.
    빈 입력란이면 Ctrl+A 가 no-op 라 부작용 없음.

- **버그 4 — 멀티라인 메시지 paste verify 에서 CRLF / LF 비교 미스매치**
  - 증상: `'1\n2\n3'` paste 후 RichEdit 텍스트가 `'1\r\n2\r\n3'` 으로
    돌아와 strict equality 비교 fail. 메시지는 paste 됐는데 우리가 못 알아봄.
  - 원인: RichEdit 은 paste 받은 LF 를 내부 표준 (CRLF) 로 변환해 저장. 우리
    메시지는 Python LF 그대로 가지고 있어 비교가 안 맞는다.
  - Fix: `_normalize_newlines` 가 비교 양쪽의 `\r\n` 과 `\r` 단독을 `\n` 으로
    정규화. paste 검증과 전송 검증 모두에 적용.

- 추가로 검증된 면역 케이스 (수정 불필요, 모두 PASS):
  - 빈 메시지 (`""`) → `KakaoWinError` 로 명시적 거부.
  - 공백만 있는 메시지 (`"    "`) → 정상 전송.
  - 1000 자 ASCII 메시지 → paste, 전송 모두 정상.
  - 시작/끝에 `\n` 만 있는 메시지 → 정상.
  - 클립보드 보존: sentinel 값 set → step7 실행 → 종료 후 sentinel 그대로
    복원 (best-effort 확인).
  - 0.5 s 간격으로 3 회 연속 전송 → race condition 없이 모두 PASS.
  - 친구 탭(1) / 채팅 탭(2) 둘 다 full pipeline PASS.
