"""카카오톡 친구추가 자동화 진입점 (macOS 전용).

현재 구현 범위:
Step 1 — 접근성 권한 확인 후 이미 실행 중인 카카오톡을 frontmost 로
Step 2 — 기존 macOS 카카오톡 단축키인 Command+1 로 친구 탭 포커스

다음 단계에서 친구추가 버튼/검색/확정 흐름을 이 파일에 이어 붙인다.
"""

from __future__ import annotations

import sys

from kakao_mac import (
    KakaoMacError,
    TAB_FRIENDS,
    _ensure_macos,
    ensure_accessibility_or_exit,
    step1_activate_kakao,
    step2_focus_tab,
)


def step2_focus_friends_tab() -> None:
    """친구추가의 시작점인 친구 탭으로 이동."""
    step2_focus_tab(TAB_FRIENDS)


def prepare_friend_add() -> None:
    """친구추가 자동화를 시작할 수 있도록 카카오톡 친구 탭까지 이동."""
    step1_activate_kakao()
    step2_focus_friends_tab()
    print("[친구추가] 친구 탭 진입 준비를 완료했습니다.")


def main() -> int:
    try:
        _ensure_macos()
        ensure_accessibility_or_exit()
        prepare_friend_add()
    except KakaoMacError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
