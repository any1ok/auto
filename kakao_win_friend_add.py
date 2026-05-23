"""카카오톡 친구 추가 자동화 준비 단계 (Windows 전용).

현재 파일은 친구 추가 플로우의 Windows 진입점이다. 먼저 기존 발송 로직
(`kakao_win.py`)에서 검증된 방식으로 아래 단계를 수행한다.

Step 1: 카카오톡 메인 창을 foreground 로 보장.
Step 2: 친구 탭으로 이동.
Step 3: 친구 추가 팝오버를 연다. 이미 열려 있으면 다시 열지 않는다.

단축키 확인 메모:
- 카카오 고객센터 단축키 표에서 `Ctrl + A` 는 "친구 추가"로 확인됨.
- `Ctrl + Shift + M` 은 "메인창 열기"로 확인됨.
- Windows PC 카카오톡에서 친구 탭으로 바로 가는 절대 단축키는 확인되지 않아,
  친구 탭 이동은 기존 `kakao_win.py`의 EVA_Window 패널 감지 + `Ctrl+Tab`
  반복 방식을 그대로 사용한다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
from typing import Optional

from kakao_win import (
    FOREGROUND_TIMEOUT_S,
    KakaoWinError,
    TAB_FRIENDS,
    _ensure_windows,
    _enum_direct_children,
    _enum_kakao_windows,
    _force_foreground,
    _get_class_name,
    _load_win32,
    _send_ctrl_a,
    step1_activate_kakao,
    step2_focus_tab,
    wait_for_foreground,
)


FRIEND_ADD_WINDOW_CLASS = "EVA_Window_Dblclk"
FRIEND_ADD_OPEN_TIMEOUT_S = 1.5
FRIEND_ADD_OPEN_POLL_INTERVAL_S = 0.05
FRIEND_ADD_MIN_VISIBLE_EDITS = 2
FRIEND_ADD_MIN_WIDTH = 240
FRIEND_ADD_MAX_WIDTH = 460
FRIEND_ADD_MIN_HEIGHT = 320
FRIEND_ADD_MAX_HEIGHT = 680
KAKAO_EDIT_CLASS = "Edit"


def _window_text(hwnd: int) -> str:
    user32, _ = _load_win32()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _window_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    user32, _ = _load_win32()
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL

    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _is_window_enabled(hwnd: int) -> bool:
    user32, _ = _load_win32()
    user32.IsWindowEnabled.argtypes = [wt.HWND]
    user32.IsWindowEnabled.restype = wt.BOOL
    return bool(user32.IsWindowEnabled(hwnd))


def _window_size(hwnd: int) -> Optional[tuple[int, int]]:
    rect = _window_rect(hwnd)
    if rect is None:
        return None
    left, top, right, bottom = rect
    return right - left, bottom - top


def _enum_descendants(parent_hwnd: int) -> list[int]:
    results: list[int] = []
    pending = list(_enum_direct_children(parent_hwnd))
    while pending:
        hwnd = pending.pop(0)
        results.append(hwnd)
        pending.extend(_enum_direct_children(hwnd))
    return results


def _visible_edit_count(hwnd: int) -> int:
    user32, _ = _load_win32()
    count = 0
    for child in _enum_descendants(hwnd):
        if _get_class_name(child) == KAKAO_EDIT_CLASS and user32.IsWindowVisible(child):
            count += 1
    return count


def _looks_like_friend_add_window(hwnd: int) -> bool:
    user32, _ = _load_win32()
    if not user32.IsWindowVisible(hwnd):
        return False
    if not _is_window_enabled(hwnd):
        return False
    if _get_class_name(hwnd) != FRIEND_ADD_WINDOW_CLASS:
        return False
    if _window_text(hwnd):
        return False

    size = _window_size(hwnd)
    if size is None:
        return False
    width, height = size
    if not (FRIEND_ADD_MIN_WIDTH <= width <= FRIEND_ADD_MAX_WIDTH):
        return False
    if not (FRIEND_ADD_MIN_HEIGHT <= height <= FRIEND_ADD_MAX_HEIGHT):
        return False

    return _visible_edit_count(hwnd) >= FRIEND_ADD_MIN_VISIBLE_EDITS


def _find_friend_add_window(
    exclude_hwnds: Optional[set[int]] = None,
) -> Optional[int]:
    exclude_hwnds = exclude_hwnds or set()
    for hwnd, _title, _visible, _iconic in _enum_kakao_windows():
        if hwnd in exclude_hwnds:
            continue
        if _looks_like_friend_add_window(hwnd):
            return hwnd
    return None


def _dump_visible_kakao_windows_to_stderr() -> None:
    print("[Step 3] KakaoTalk visible top-level window 목록:", file=sys.stderr)
    for hwnd, title, visible, iconic in _enum_kakao_windows():
        if not visible:
            continue
        rect = _window_rect(hwnd)
        size = _window_size(hwnd)
        edits = _visible_edit_count(hwnd)
        print(
            f"  - hwnd=0x{hwnd:08X} class={_get_class_name(hwnd)!r} "
            f"title={title!r} enabled={_is_window_enabled(hwnd)} "
            f"iconic={iconic} rect={rect} size={size} visible_edits={edits}",
            file=sys.stderr,
        )


def step1_focus_kakao_main() -> int:
    """카카오톡 메인 창을 foreground 로 만들고 hwnd 를 반환."""
    return step1_activate_kakao()


def step2_focus_friends_tab(hwnd: int) -> None:
    """카카오톡 메인 창에서 친구 탭으로 이동."""
    step2_focus_tab(hwnd, TAB_FRIENDS)


def step3_open_friend_add_popover(hwnd: int) -> int:
    """친구 추가 팝오버를 열고 팝오버 hwnd 를 반환.

    이미 팝오버가 열려 있으면 Ctrl+A 를 다시 보내지 않는다. 카카오톡 PC 는
    팝오버가 열린 동안 메인 창을 disabled 로 바꾸므로, 이미 열린 상태에서
    메인 창을 다시 foreground 로 잡거나 Step 2 를 반복하면 실패할 수 있다.
    """
    existing = _find_friend_add_window()
    if existing is not None:
        _force_foreground(existing)
        print(
            f"[Step 3] 친구 추가 창이 이미 열려 있습니다. "
            f"(hwnd=0x{existing:08X})"
        )
        return existing

    _force_foreground(hwnd)
    if not wait_for_foreground(hwnd):
        raise KakaoWinError(
            f"카카오톡이 {FOREGROUND_TIMEOUT_S}s 안에 foreground 가 되지 "
            "않았습니다. (친구 추가 창 열기 직전 재확인 실패)"
        )

    baseline = {h for h, _title, _visible, _iconic in _enum_kakao_windows()}
    _send_ctrl_a()

    deadline = time.monotonic() + FRIEND_ADD_OPEN_TIMEOUT_S
    last_candidate = None
    while time.monotonic() < deadline:
        opened = _find_friend_add_window(exclude_hwnds=baseline)
        if opened is None:
            opened = _find_friend_add_window()
        if opened is not None:
            print(
                f"[Step 3] 친구 추가 창을 열었습니다. "
                f"(Ctrl+A, hwnd=0x{opened:08X})"
            )
            return opened

        visible_candidates = [
            h for h, _title, visible, _iconic in _enum_kakao_windows()
            if visible and _get_class_name(h) == FRIEND_ADD_WINDOW_CLASS
        ]
        if visible_candidates:
            last_candidate = visible_candidates[0]
        time.sleep(FRIEND_ADD_OPEN_POLL_INTERVAL_S)

    _dump_visible_kakao_windows_to_stderr()
    if last_candidate is not None:
        raise KakaoWinError(
            "Ctrl+A 후 친구 추가 창 후보는 보였지만, 예상 구조 "
            f"(visible Edit {FRIEND_ADD_MIN_VISIBLE_EDITS}개 이상, "
            "빈 title, 적정 크기)에 맞지 않았습니다. "
            f"마지막 후보 hwnd=0x{last_candidate:08X}."
        )
    raise KakaoWinError(
        "Ctrl+A 후 친구 추가 창이 열리지 않았습니다. 카카오톡 단축키 또는 "
        "친구 탭 UI 구조가 바뀌었을 수 있습니다."
    )


def prepare_friend_add_window() -> int:
    """친구 추가를 시작할 수 있도록 친구 추가 팝오버까지 연다."""
    existing = _find_friend_add_window()
    if existing is not None:
        _force_foreground(existing)
        print(
            f"[Step 3] 친구 추가 창이 이미 열려 있습니다. "
            f"(hwnd=0x{existing:08X}, Step 1/2 생략)"
        )
        return existing

    hwnd = step1_focus_kakao_main()
    step2_focus_friends_tab(hwnd)
    return step3_open_friend_add_popover(hwnd)


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
