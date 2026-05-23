# 카카오톡 자동화 (macOS)

Python 으로 카카오톡 데스크톱 앱을 단계별로 자동화합니다.
**현재는 macOS 전용** (Windows 는 추후 별도 파일).

## 스텝

- [x] Step 1 — 이미 실행 중인 카카오톡을 frontmost 로
- [x] Step 2 — `⌘+1`(친구) / `⌘+2`(채팅) 탭 포커스
- [x] Step 3 — 현재 탭 상단 검색창에 텍스트 입력 (Enter 미입력)
- [x] Step 4 — 검색 결과의 첫 데이터 row 이름이 query 와 **정확히 일치**하는지 확인
- [x] Step 5 — 일치 확인된 첫 결과(채팅방) 를 Return 으로 열기
- [x] Step 6 — 카카오톡 windows 의 AXTitle 에 query 가 떴는지로 **열림 검증**
- [x] Step 7 — 열린 채팅방에 메시지를 `⌘V` 로 붙여넣고 `Return` 으로 전송

## 요구사항

- macOS, Python 3.8+
- 카카오톡 데스크톱 앱을 미리 실행
- 외부 라이브러리 없음 (`osascript`, `pbcopy`, `ctypes` 만 사용)

## 사용법

```bash
# 대화형 — 탭(1/2), 검색어, 보낼 메시지를 차례로 묻습니다. (메시지 빈 줄이면 방만 열고 끝)
python3 kakao_mac.py

# 인자로 바로 지정 — 3번째 인자(메시지) 생략 시 방만 열고 끝
python3 kakao_mac.py 1 "홍길동"                  # 친구 탭, 방만 열기
python3 kakao_mac.py 2 "회사"                    # 채팅 탭, 방만 열기
python3 kakao_mac.py 2 "홍길동" "안녕하세요"     # 채팅 탭, 방 열고 메시지 전송
```

성공 시 출력:

```
[Step 1] 카카오톡을 포커스했습니다.
[Step 2] 채팅 탭으로 포커스했습니다. (⌘+2)
[Step 3] 검색창에 입력 완료: '홍길동'
[Step 4] 첫 데이터 row '홍길동' == '홍길동' → 일치 (AX row 인덱스 = 2).
[Step 5] ↓ × 2 → Return 으로 채팅방을 열었습니다.
[Step 6] '홍길동' 윈도우 발견 (정확 일치) → 채팅방 열림 확인.
[Step 7] 메시지 전송 완료: '안녕하세요'
```

- 검색 결과의 첫 데이터 row 가 query 와 다르면 Step 5/6/7 은 실행되지 않습니다 (엉뚱한 방을 안 열기 위함).
- Step 6 가 열림 검증에 실패하면 Step 7 은 일부러 실행되지 않습니다 (엉뚱한 창에 메시지가 가는 사고 방지).
- 메시지 인자/입력이 비어 있으면 Step 7 만 건너뛰고 방 열기까지로 끝납니다.

## 권한

스크립트는 시작 시 `AXIsProcessTrusted()` 를 ctypes 로 호출해 접근성 권한을 점검합니다.
권한이 없으면 **시스템 설정 패널을 자동으로 열고 종료 코드 3** 으로 종료합니다.

- **손쉬운 사용 (Accessibility)** — `key code` / `keystroke` 전송에 필수
- **자동화 (Automation)** — 터미널/IDE 가 `KakaoTalk`, `System Events` 를 제어하도록 허용

권한을 추가한 뒤 터미널/IDE 를 재시작해야 반영될 수 있습니다.

## 설계 노트 (실패 회피용)

- 권한 점검은 `AXIsProcessTrusted()` 만. AppleScript `UI elements enabled` 는 false positive 가 있어 쓰지 않음.
- 모든 `input()` 은 Step 1 이전에 받음. 단계 중간에 입력받으면 터미널로 포커스가 빠짐.
- `activate` 직후 sleep 대신 `frontmost` 프로세스 이름을 40 ms 간격, 1.5 s 타임아웃으로 폴링.
- `⌘+F` / `⌘+A` / `⌘+V` 는 `keystroke "f"` 가 아닌 `key code 3 / 0 / 9 using command down` 사용. (한글 IME 가 켜져 있으면 `f` → `ㄹ` 로 번역됨)
- 한글 검색어는 직접 타이핑하지 않고 `pbcopy` + `⌘+V` 로 붙여넣기.
- 검색창 clear + paste(`⌘+F → ⌘+A → delete → ⌘+V`) 는 단일 `osascript` 호출 안에서 batch 로 전송.
- Step 4 는 `scroll area > {outline|table|list} > row` 를 5단계 fallback 으로 훑어 첫 데이터 row (카운트 배지 `"1"`/`"999+"` 류는 건너뜀) 의 이름을 뽑고, query 와 정확히 일치하는지만 확인. 검색 paste 직후 결과가 갱신될 시간을 주기 위해 초기 delay + (rowCount|firstName|firstRowIdx) 스냅샷이 두 번 연속 같아질 때까지 폴링.
- Step 5 는 클릭이 아니라 `key code 125` (↓) × first_idx → `key code 36` (Return) 만 사용. 카카오톡 Mac 검색창은 입력 직후 첫 결과를 자동 하이라이트하지 않아서 Return 만 보내면 무시된다. 검색창에서 ↓ 를 누르면 결과 리스트의 다음 row 로 포커스가 이동하므로 Step 4 가 알려준 1-indexed `first_idx` 만큼 ↓ 를 보낸 뒤 Return 한다. (배지 row `"1"`/`"999+"` 도 키보드 navigable 이라 first_idx 가 곧 ↓ 횟수와 같음.) 모든 키 코드는 단일 osascript 안에서 batch 전송 → 중간에 터미널이 키를 가로챌 여지 없음. `keystroke` 가 아닌 `key code` 라 한글 IME 영향 없음.
- Step 6 은 카카오톡 프로세스의 `windows` 의 `name` (AXTitle) 만 본다. 새 채팅방은 별도 윈도우로 뜨므로 어떤 윈도우의 타이틀이 query 와 같으면 (= `WINDOW_TITLE_EXACT`) 열림으로 확정, 포함하기만 하면 (= `WINDOW_TITLE_CONTAINS`) 약한 확정 (타이틀 장식 가능성). EXACT 가 보이면 즉시 break, 아니면 최대 `OPEN_VERIFY_MAX_ITERS` 회 폴링. 매 회 모든 윈도우 이름을 함께 모아 마지막 시도분을 stderr 에 찍어 디버깅을 쉽게 한다.
- Step 7 은 Step 3 와 100% 같은 키 입력 패턴 (`pbcopy` + `⌘V` + `Return` 을 단일 osascript batch). 채팅방을 열면 카톡이 메시지 입력칸에 자동 포커스해 두므로 별도 포커스 이동 X. `Return` 은 카톡 기본 설정 'Return = 보내기' 를 전제. 환경설정에서 'Return = 줄바꿈' 으로 바꾼 경우 줄만 바뀌고 전송이 안 된다. Step 6 이 실패하면 Step 7 은 일부러 실행 안 함 (엉뚱한 창에 메시지 가는 사고 방지).
