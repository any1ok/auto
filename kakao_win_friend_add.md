# 카카오톡 친구 추가 자동화 준비 (Windows)

`kakao_win_friend_add.py` 는 친구 추가 플로우를 별도 파일로 분리하기 위한
Windows 전용 진입점입니다. 현재는 기존 `kakao_win.py` 의 검증된 창 제어
로직을 재사용해 연락처 입력과 친구 추가 확정까지 수행합니다.

## 스텝

- [x] Step 1 — 이미 실행 중인 카카오톡 메인 창을 foreground 로 보장
- [x] Step 2 — 친구 탭으로 이동
- [x] Step 3 — 친구 추가 창 열기 (`Ctrl + A`, 이미 열림 감지)
- [x] Step 4 — 연락처 탭에서 이름 / 전화번호 입력
- [x] Step 5 — `친구 추가` 확정 후 팝오버 닫힘 / 오류 상태 판정 및 닫기


## 사용법

```bat
:: 이름/전화번호를 물어본 뒤 연락처로 친구 추가 시도
python kakao_win_friend_add.py

:: 인자로 바로 연락처 친구 추가 시도
python kakao_win_friend_add.py "테스트1" "01011111111"
```

성공 시 출력 예:

```text
[Step 1] 카카오톡을 포커스했습니다.
[Step 2] 친구 탭으로 포커스했습니다. (이미 활성 탭, Ctrl+Tab × 0)
[Step 3] 친구 추가 창을 열었습니다. (Ctrl+A, hwnd=0x...)
[Step 4] 연락처 입력 완료: name='테스트2', phone='01022222222'
[Step 5] 친구 추가 버튼을 눌렀고 후속 팝오버를 닫았습니다.
```

친구 추가 창이 이미 열려 있으면 메인 창이 disabled 상태라 Step 1/2 를
다시 수행하지 않고 열린 창을 그대로 사용합니다.

```text
[Step 3] 친구 추가 창이 이미 열려 있습니다. (hwnd=0x..., Step 1/2 생략)
```

이미 다른 탭이 활성 상태라면 `Ctrl+Tab` 을 필요한 횟수만큼 보내 친구 탭에
도달합니다.

## 요구사항

- Windows 10 이상, Python 3.8+
- 카카오톡 데스크톱 앱이 미리 실행되어 있어야 함
- 외부 라이브러리 없음 (`kakao_win.py` 의 `ctypes` 기반 Win32 로직 재사용)

## 단축키 확인

- 카카오 고객센터 단축키 표에서 `Ctrl + A` 는 `Add friend` 로 확인됨:
  <https://cs.kakao.com/helps_html/1073183088?locale=ko>
- 같은 표에서 `Ctrl + Shift + M` 은 `Open Main Window` 로 확인됨.
- Windows PC 카카오톡에서 친구 탭으로 바로 이동하는 절대 단축키는 확인되지 않음.

따라서 친구 탭 이동은 단축키 하나에 의존하지 않고, 기존 `kakao_win.py` 의
`EVA_Window` 패널 감지 + `Ctrl+Tab` 반복 방식을 그대로 사용합니다.

## 설계 노트

- 새 파일은 `kakao_win.py` 의 `step1_activate_kakao()` 와 `step2_focus_tab()`
  을 import 해서 재사용합니다. 발송 로직과 친구 추가 로직의 Windows 창 제어
  기준을 한 곳에 유지하기 위함입니다.
- Step 1 은 `EnumWindows` 로 `KakaoTalk.exe` 소유 top-level 창을 찾고,
  `AttachThreadInput` + `SetForegroundWindow` 로 메인 창 foreground 를 보장합니다.
- Step 2 는 카카오톡 메인 창 내부의 `EVA_ChildWindow` 아래 `EVA_Window`
  패널 중 visible 인 패널을 현재 탭으로 판단합니다. 목표인 친구 탭(idx 0)에
  도달할 때까지 `SendInput` 으로 `Ctrl+Tab` 을 보냅니다.
- Step 3 은 실행 전 이미 열린 친구 추가 창을 먼저 찾습니다. 친구 추가 창은
  visible top-level `EVA_Window_Dblclk` 이고, 빈 title, 적정 팝오버 크기,
  visible 표준 `Edit` 입력칸 2개 이상이라는 구조로 식별합니다.
- 친구 추가 창이 없으면 친구 탭 foreground 를 재확인한 뒤 `SendInput` 으로
  `Ctrl+A` 를 보내고, 새로 뜬 팝오버를 위 구조로 폴링 검증합니다.
- Step 4 는 연락처 탭의 visible `Edit` 2개를 이름/전화번호 입력칸으로 잡고,
  카카오톡 내부 validation 이벤트가 발생하도록 클립보드 + `Ctrl+V` 로 입력합니다.
  이미 ID 탭이 열려 있으면 연락처 탭으로 되돌립니다.
- Step 5 는 전화번호 입력칸에서 `Enter` 로 조회/오류 표시를 트리거합니다.
  valid 번호에서 프로필 결과가 뜨면 `Tab` + `Enter` 로 `친구 추가` 버튼을
  누릅니다. 성공 후 프로필 선택 같은 후속 팝오버가 남으면 닫고, invalid 번호처럼
  오류 상태로 팝오버가 유지되면 실패로 판정한 뒤 닫습니다.
- 카카오톡이 관리자 권한으로 실행 중이면 스크립트도 같은 권한으로 실행해야
  합니다. 권한 레벨이 다르면 Windows UIPI 때문에 foreground 전환이나 입력이
  차단될 수 있습니다.

## 테스트 결과

```bat
python kakao_win_friend_add.py "테스트1" "01011111111"
```

결과: 오류 상태로 판정하고 팝오버를 닫음. 종료 코드 `1`. 재검증 기준 전체 실행 약 2.9초.

```bat
python kakao_win_friend_add.py "테스트2" "01022222222"
```

결과: `친구 추가` 버튼 클릭 후 후속 팝오버까지 닫음. 종료 코드 `0`. 재검증 기준 전체 실행 약 1.6초.
