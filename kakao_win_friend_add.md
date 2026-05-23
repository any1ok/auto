# 카카오톡 친구 추가 자동화 준비 (Windows)

`kakao_win_friend_add.py` 는 친구 추가 플로우를 별도 파일로 분리하기 위한
Windows 전용 진입점입니다. 현재는 친구 추가 창을 실제로 여는 단계 전에,
기존 `kakao_win.py` 의 검증된 방법으로 아래 두 단계만 수행합니다.

## 스텝

- [x] Step 1 — 이미 실행 중인 카카오톡 메인 창을 foreground 로 보장
- [x] Step 2 — 친구 탭으로 이동
- [ ] Step 3 — 친구 추가 창 열기 (`Ctrl + A` 후보)
- [ ] Step 4 — 연락처/ID 입력 방식 결정 및 구현

## 사용법

```bat
python kakao_win_friend_add.py
```

성공 시 출력 예:

```text
[Step 1] 카카오톡을 포커스했습니다.
[Step 2] 친구 탭으로 포커스했습니다. (이미 활성 탭, Ctrl+Tab × 0)
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
- 카카오톡이 관리자 권한으로 실행 중이면 스크립트도 같은 권한으로 실행해야
  합니다. 권한 레벨이 다르면 Windows UIPI 때문에 foreground 전환이나 입력이
  차단될 수 있습니다.

## 다음 구현 후보

다음 단계는 Step 2 직후 `Ctrl + A` 를 `SendInput` 으로 보내 친구 추가 창이
뜨는지 검증하는 방식이 가장 단순합니다. 단, 창 타이틀/클래스명 검증이 먼저
붙어야 이후 연락처 또는 카카오톡 ID 입력 단계가 안정적으로 이어집니다.
