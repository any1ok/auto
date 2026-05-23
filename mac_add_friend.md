# 카카오톡 친구추가 자동화 (macOS)

`kakao_mac_add_friend.py` 는 카카오톡 macOS 앱에서 친구추가 자동화를 시작하기 위한
별도 진입 파일입니다.

현재는 친구추가 전체 플로우가 아니라, 친구추가를 진행할 수 있는 시작 상태까지
보장합니다.

## 스텝

- [x] Step 1 — 접근성 권한 확인 후 이미 실행 중인 카카오톡을 frontmost 로
- [x] Step 2 — `⌘+1` 로 친구 탭 포커스
- [ ] Step 3 — 친구추가 버튼 또는 메뉴 진입
- [ ] Step 4 — ID / 전화번호 / 검색어 입력
- [ ] Step 5 — 검색 결과 확인 후 추가 확정

## 요구사항

- macOS, Python 3.8+
- 카카오톡 데스크톱 앱을 미리 실행
- 터미널/IDE 또는 Python 실행 파일에 손쉬운 사용(Accessibility) 권한 부여
- 외부 라이브러리 없음 (`kakao_mac.py` 의 기존 `osascript`, `ctypes` 기반 로직 재사용)

## 사용법

```bash
python3 kakao_mac_add_friend.py
```

성공 시 출력:

```text
[Step 1] 카카오톡을 포커스했습니다.
[Step 2] 친구 탭으로 포커스했습니다. (⌘+1)
[친구추가] 친구 탭 진입 준비를 완료했습니다.
```

## 구현 방식

- 접근성 권한 확인은 기존 `kakao_mac.py` 의 `ensure_accessibility_or_exit()` 를 그대로 사용합니다.
- 카카오톡 실행 확인과 frontmost 보장은 기존 `step1_activate_kakao()` 를 그대로 사용합니다.
- 친구 탭 이동은 기존 `step2_focus_tab("1")` 을 감싼 `step2_focus_friends_tab()` 으로 처리합니다.
- 카카오톡이 실행되어 있지 않거나 frontmost 전환에 실패하면 `KakaoMacError` 로 종료합니다.

## 단축키 근거

카카오 고객센터의 PC/태블릿/워치 이용 카테고리 내 `Mac 버전 단축키가 궁금해요.`
항목에서 macOS 카카오톡 단축키가 다음처럼 안내됩니다.

- 친구 탭 열기: `⌘ + 1`
- 채팅 탭 열기: `⌘ + 2`
- 더보기 탭 열기: `⌘ + 3`

참고 URL: <https://cs.kakao.com/helps?service=8&category=1056&locale=ko>

## 다음 구현 후보

친구 탭 진입 이후의 친구추가 버튼에 공식 단축키가 확인되지 않으면, 기존 macOS 파일의
방식과 동일하게 `System Events` 접근성 트리에서 버튼을 찾고 클릭하는 방식이 가장
확실한 다음 단계입니다.
