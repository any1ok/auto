"""카카오톡 친구 추가 자동화 준비 단계 (Windows 전용).

현재 파일은 친구 추가 플로우의 Windows 진입점이다. 먼저 기존 발송 로직
(`kakao_win.py`)에서 검증된 방식으로 아래 두 단계만 수행한다.

Step 1: 카카오톡 메인 창을 foreground 로 보장.
Step 2: 친구 탭으로 이동.

단축키 확인 메모:
- 카카오 고객센터 단축키 표에서 `Ctrl + A` 는 "친구 추가"로 확인됨.
- `Ctrl + Shift + M` 은 "메인창 열기"로 확인됨.
- Windows PC 카카오톡에서 친구 탭으로 바로 가는 절대 단축키는 확인되지 않아,
  친구 탭 이동은 기존 `kakao_win.py`의 EVA_Window 패널 감지 + `Ctrl+Tab`
  반복 방식을 그대로 사용한다.
"""

from __future__ import annotations

import sys

from kakao_win import (
    KakaoWinError,
    TAB_FRIENDS,
    _ensure_windows,
    step1_activate_kakao,
    step2_focus_tab,
)


def step1_focus_kakao_main() -> int:
    """카카오톡 메인 창을 foreground 로 만들고 hwnd 를 반환."""
    return step1_activate_kakao()


def step2_focus_friends_tab(hwnd: int) -> None:
    """카카오톡 메인 창에서 친구 탭으로 이동."""
    step2_focus_tab(hwnd, TAB_FRIENDS)


def prepare_friend_add_window() -> int:
    """친구 추가를 시작할 수 있도록 카카오톡 메인 창과 친구 탭을 준비."""
    hwnd = step1_focus_kakao_main()
    step2_focus_friends_tab(hwnd)
    return hwnd


def main() -> int:
    try:
        _ensure_windows()
        prepare_friend_add_window()
    except KakaoWinError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
