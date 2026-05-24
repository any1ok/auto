"""카카오톡 친구 추가 자동화 준비 단계 (Windows 전용).

현재 파일은 친구 추가 플로우의 Windows 진입점이다. 먼저 기존 발송 로직
(`kakao_win.py`)에서 검증된 방식으로 아래 단계를 수행한다.

Step 1: 카카오톡 메인 창을 foreground 로 보장.
Step 2: 친구 탭으로 이동.
Step 3: 친구 추가 팝오버를 연다. 이미 열려 있으면 다시 열지 않는다.
Step 4: 연락처 탭에서 이름 / 전화번호를 입력하고 친구 추가를 확정한다.

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
    VK_ESCAPE,
    VK_RETURN,
    VK_TAB,
    _ensure_windows,
    _clipboard_get_unicode,
    _clipboard_set_unicode,
    _enum_direct_children,
    _enum_kakao_windows,
    _force_focus,
    _force_foreground,
    _get_class_name,
    _get_edit_text,
    _load_win32,
    _send_ctrl_a,
    _send_ctrl_v,
    _send_vk_sendinput,
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
KAKAO_CHILD_WINDOW_CLASS = "EVA_ChildWindow"
FRIEND_ADD_FILL_VERIFY_TIMEOUT_S = 1.0
FRIEND_ADD_FILL_VERIFY_POLL_INTERVAL_S = 0.03
FRIEND_ADD_SUBMIT_INITIAL_WAIT_S = 1.1
FRIEND_ADD_SUBMIT_VERIFY_TIMEOUT_S = 1.0
FRIEND_ADD_CLOSE_TIMEOUT_S = 0.8
FRIEND_ADD_ERROR_CONFIRM_DELAY_S = 0.05
WM_CLOSE = 0x0010
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

_extra_user32_bound = False


def _load_user32_extra() -> ctypes.WinDLL:
    """kakao_win 공용 바인딩에 없는 작은 user32 API 들을 한 번만 지정."""
    global _extra_user32_bound
    user32, _ = _load_win32()
    if _extra_user32_bound:
        return user32

    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindow.restype = wt.BOOL
    user32.IsWindowEnabled.argtypes = [wt.HWND]
    user32.IsWindowEnabled.restype = wt.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wt.BOOL
    user32.mouse_event.argtypes = [
        wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p,
    ]
    user32.mouse_event.restype = None

    _extra_user32_bound = True
    return user32


def _window_text(hwnd: int) -> str:
    user32, _ = _load_win32()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _window_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    user32 = _load_user32_extra()
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _is_window_enabled(hwnd: int) -> bool:
    user32 = _load_user32_extra()
    return bool(user32.IsWindowEnabled(hwnd))


def _is_window_visible(hwnd: int) -> bool:
    user32, _ = _load_win32()
    return bool(user32.IsWindowVisible(hwnd))


def _is_window(hwnd: int) -> bool:
    user32 = _load_user32_extra()
    return bool(user32.IsWindow(hwnd))


def _window_size(hwnd: int) -> Optional[tuple[int, int]]:
    rect = _window_rect(hwnd)
    if rect is None:
        return None
    left, top, right, bottom = rect
    return right - left, bottom - top


def _click_at_screen_point(x: int, y: int) -> None:
    user32 = _load_user32_extra()
    if not user32.SetCursorPos(x, y):
        raise KakaoWinError("마우스 커서 이동에 실패했습니다.")
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)


def _click_relative(hwnd: int, x: int, y: int) -> None:
    rect = _window_rect(hwnd)
    if rect is None:
        raise KakaoWinError(f"창 좌표를 읽지 못했습니다 (hwnd=0x{hwnd:08X}).")
    left, top, _right, _bottom = rect
    _click_at_screen_point(left + x, top + y)


def _click_center(hwnd: int) -> None:
    rect = _window_rect(hwnd)
    if rect is None:
        raise KakaoWinError(f"창 좌표를 읽지 못했습니다 (hwnd=0x{hwnd:08X}).")
    left, top, right, bottom = rect
    _click_at_screen_point((left + right) // 2, (top + bottom) // 2)


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


def _looks_like_friend_flow_popup(hwnd: int) -> bool:
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

    return True


def _looks_like_friend_add_window(hwnd: int) -> bool:
    if not _looks_like_friend_flow_popup(hwnd):
        return False
    return _visible_edit_count(hwnd) >= FRIEND_ADD_MIN_VISIBLE_EDITS


def _find_friend_flow_popup() -> Optional[int]:
    for hwnd, _title, _visible, _iconic in _enum_kakao_windows():
        if _looks_like_friend_flow_popup(hwnd):
            return hwnd
    return None


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


def _reuse_or_close_existing_flow_popup(detail: str = "") -> Optional[int]:
    existing = _find_friend_flow_popup()
    if existing is None:
        return None

    switched_to_contact = False
    if _find_contact_fields(existing) is None and _visible_edit_count(existing) == 1:
        _force_foreground(existing)
        _click_relative(existing, 92, 142)
        switched_to_contact = _find_contact_fields(existing) is not None

    if _find_contact_fields(existing) is not None:
        _force_foreground(existing)
        note = "ID 탭 → 연락처 탭, " if switched_to_contact else ""
        extra = f", {detail}" if detail else ""
        print(
            f"[Step 3] 친구 추가 창이 이미 열려 있습니다. "
            f"({note}hwnd=0x{existing:08X}{extra})"
        )
        return existing

    _close_friend_flow_popup(existing)
    return None


def _wait_friend_flow_popup_closed(
    hwnd: int,
    timeout_s: float = FRIEND_ADD_CLOSE_TIMEOUT_S,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _is_window(hwnd) or not _is_window_visible(hwnd):
            return True
        time.sleep(FRIEND_ADD_OPEN_POLL_INTERVAL_S)
    return not _is_window(hwnd) or not _is_window_visible(hwnd)


def _close_friend_flow_popup(hwnd: int) -> bool:
    if not _is_window(hwnd) or not _is_window_visible(hwnd):
        return True

    _force_foreground(hwnd)
    _send_vk_sendinput(VK_ESCAPE)
    if _wait_friend_flow_popup_closed(hwnd):
        return True

    _send_vk_sendinput(VK_ESCAPE)
    if _wait_friend_flow_popup_closed(hwnd):
        return True

    user32, _ = _load_win32()
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return _wait_friend_flow_popup_closed(hwnd)


def _close_and_report_error(hwnd: int) -> bool:
    _close_friend_flow_popup(hwnd)
    print(
        "[Step 5] 친구 추가 실패: 오류 상태로 판단해 팝오버를 닫았습니다.",
        file=sys.stderr,
    )
    return False


def _find_contact_fields(
    popover_hwnd: int,
) -> Optional[tuple[int, list[int]]]:
    user32, _ = _load_win32()
    for child in _enum_direct_children(popover_hwnd):
        if _get_class_name(child) != KAKAO_CHILD_WINDOW_CLASS:
            continue
        if not user32.IsWindowVisible(child):
            continue
        edits = [
            h for h in _enum_direct_children(child)
            if _get_class_name(h) == KAKAO_EDIT_CLASS
            and user32.IsWindowVisible(h)
        ]
        if len(edits) >= 2:
            edits.sort(key=lambda h: (_window_rect(h) or (0, 0, 0, 0))[1])
            return child, edits[:2]
    return None


def _ensure_contact_fields(popover_hwnd: int) -> tuple[int, list[int]]:
    found = _find_contact_fields(popover_hwnd)
    if found is not None:
        return found

    # 이미 열린 팝오버가 ID 탭에 있을 수 있다. 연락처 탭은 팝오버 기준
    # 왼쪽 상단의 첫 탭이라 상대 좌표 클릭으로 되돌린다.
    if _visible_edit_count(popover_hwnd) == 1:
        _force_foreground(popover_hwnd)
        _click_relative(popover_hwnd, 92, 142)
        deadline = time.monotonic() + FRIEND_ADD_OPEN_TIMEOUT_S
        while time.monotonic() < deadline:
            found = _find_contact_fields(popover_hwnd)
            if found is not None:
                return found
            time.sleep(FRIEND_ADD_OPEN_POLL_INTERVAL_S)

    raise KakaoWinError(
        "친구 추가 연락처 입력칸을 찾지 못했습니다. "
        "팝오버가 연락처 탭이 아니거나 카카오톡 UI 구조가 바뀌었을 수 있습니다."
    )


def _has_profile_result(popover_hwnd: int) -> bool:
    found = _find_contact_fields(popover_hwnd)
    if found is None:
        return _visible_edit_count(popover_hwnd) == 0
    page, _edits = found
    return not _is_window_enabled(page)


def _has_result_pane(popover_hwnd: int) -> bool:
    user32, _ = _load_win32()
    for child in _enum_direct_children(popover_hwnd):
        if _get_class_name(child) != KAKAO_CHILD_WINDOW_CLASS:
            continue
        if not user32.IsWindowVisible(child):
            continue
        rect = _window_rect(child)
        if rect is None:
            continue
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        if width >= 200 and height >= 60 and _visible_edit_count(child) == 0:
            return True
    return False


def _wait_edit_text(edit_hwnd: int, expected: str) -> tuple[bool, str]:
    deadline = time.monotonic() + FRIEND_ADD_FILL_VERIFY_TIMEOUT_S
    last = _get_edit_text(edit_hwnd)
    while time.monotonic() < deadline:
        if last == expected:
            return True, last
        time.sleep(FRIEND_ADD_FILL_VERIFY_POLL_INTERVAL_S)
        last = _get_edit_text(edit_hwnd)
    return last == expected, last


def _paste_text_into_edit(edit_hwnd: int, text: str) -> None:
    last_actual = ""
    for attempt in range(3):
        focused = _force_focus(edit_hwnd)
        if attempt > 0 or not focused:
            _click_center(edit_hwnd)
            time.sleep(0.05)
            focused = _force_focus(edit_hwnd)
        if not focused:
            print(
                f"[Step 4] 경고: 입력칸(hwnd=0x{edit_hwnd:08X}) 포커스 검증 실패. "
                f"붙여넣기 재시도 {attempt + 1}/3.",
                file=sys.stderr,
            )
        _send_ctrl_a()
        time.sleep(0.03)
        _clipboard_set_unicode(text)
        _send_ctrl_v()
        ok, last_actual = _wait_edit_text(edit_hwnd, text)
        if ok:
            return
        time.sleep(0.08)

    raise KakaoWinError(
        f"입력칸 텍스트 검증 실패: expected={text!r}, actual={last_actual!r}, "
        f"edit=0x{edit_hwnd:08X}. 포커스 또는 클립보드 입력이 다른 "
        "컨트롤로 들어갔을 수 있습니다."
    )


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
    existing_flow = _reuse_or_close_existing_flow_popup()
    if existing_flow is not None:
        return existing_flow

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
            if visible and _looks_like_friend_flow_popup(h)
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
    existing_flow = _reuse_or_close_existing_flow_popup("Step 1/2 생략")
    if existing_flow is not None:
        return existing_flow

    hwnd = step1_focus_kakao_main()
    step2_focus_friends_tab(hwnd)
    return step3_open_friend_add_popover(hwnd)


def step4_fill_contact_fields(popover_hwnd: int, name: str, phone: str) -> None:
    """연락처 탭에서 이름과 전화번호를 입력한다."""
    if not name.strip():
        raise KakaoWinError("추가할 친구 이름이 비어 있습니다.")
    if not phone.strip():
        raise KakaoWinError("추가할 전화번호가 비어 있습니다.")

    _force_foreground(popover_hwnd)
    _page, edits = _ensure_contact_fields(popover_hwnd)
    name_edit, phone_edit = edits[0], edits[1]

    saved_clip = _clipboard_get_unicode()
    try:
        _paste_text_into_edit(name_edit, name)
        _paste_text_into_edit(phone_edit, phone)
    finally:
        if saved_clip is not None:
            try:
                _clipboard_set_unicode(saved_clip)
            except KakaoWinError as e:
                print(f"[Step 4] 경고: 클립보드 복원 실패: {e}", file=sys.stderr)

    print(f"[Step 4] 연락처 입력 완료: name={name!r}, phone={phone!r}")


def step5_confirm_friend_add(popover_hwnd: int) -> bool:
    """친구 추가를 확정하고, 남는 팝오버를 닫는다.

    Windows 카카오톡은 실패 시 오류 문구를 EVA 커스텀 렌더링으로 표시하며
    팝오버를 유지한다. 성공/후속 처리 시에는 닫히거나, 이 계정처럼
    '친구에게 보여줄 프로필 선택' 팝업(visible Edit 0개)으로 넘어갈 수 있다.
    """
    _force_foreground(popover_hwnd)

    # 전화번호 Edit 에 포커스가 남아 있는 상태에서 Enter 를 보내면
    # invalid 번호는 오류 문구를 띄우고, valid 번호는 프로필 결과를 띄운다.
    _send_vk_sendinput(VK_RETURN)

    deadline = time.monotonic() + FRIEND_ADD_SUBMIT_INITIAL_WAIT_S
    current = _find_friend_flow_popup()
    while time.monotonic() < deadline:
        current = _find_friend_flow_popup()
        if current is None or _has_profile_result(current):
            break
        if _has_result_pane(current):
            time.sleep(FRIEND_ADD_ERROR_CONFIRM_DELAY_S)
            current = _find_friend_flow_popup()
            break
        time.sleep(FRIEND_ADD_OPEN_POLL_INTERVAL_S)

    if current is None:
        print("[Step 5] 친구 추가 완료: 팝오버가 닫혔습니다.")
        return True

    if not _has_profile_result(current):
        return _close_and_report_error(current)

    # valid 번호에서 프로필 결과가 보인 뒤에는 Tab → Enter 로 하단의
    # '친구 추가' 확정 버튼을 누른다. invalid 오류 화면은 위에서 바로 닫는다.
    _force_foreground(current)
    _send_vk_sendinput(VK_TAB)
    time.sleep(0.15)
    _send_vk_sendinput(VK_RETURN)

    deadline = time.monotonic() + FRIEND_ADD_SUBMIT_VERIFY_TIMEOUT_S
    while time.monotonic() < deadline:
        current = _find_friend_flow_popup()
        if current is None:
            print("[Step 5] 친구 추가 완료: 팝오버가 닫혔습니다.")
            return True
        if _visible_edit_count(current) == 0:
            _close_friend_flow_popup(current)
            print(
                "[Step 5] 친구 추가 버튼을 눌렀고 후속 팝오버를 닫았습니다."
            )
            return True
        if not _has_profile_result(current):
            break
        time.sleep(FRIEND_ADD_OPEN_POLL_INTERVAL_S)

    current = _find_friend_flow_popup()
    if current is not None:
        return _close_and_report_error(current)
    print("[Step 5] 친구 추가 완료: 팝오버가 닫혔습니다.")
    return True


def add_friend_by_contact(name: str, phone: str) -> bool:
    popover = prepare_friend_add_window()
    step4_fill_contact_fields(popover, name, phone)
    return step5_confirm_friend_add(popover)


def _prompt_name_and_phone() -> tuple[str, str]:
    name = input("추가할 친구 이름: ").rstrip("\n")
    phone = input("전화번호: ").rstrip("\n")
    return name, phone


def _print_usage() -> None:
    print(
        f"사용법: python {sys.argv[0]} [\"이름\" \"전화번호\"]\n"
        "  인자를 생략하면 이름과 전화번호를 입력받습니다.\n"
        "  예) python kakao_win_friend_add.py \"테스트1\" \"01011111111\"",
        file=sys.stderr,
    )


def main() -> int:
    args = sys.argv[1:]
    if len(args) not in (0, 2):
        _print_usage()
        return 2

    try:
        _ensure_windows()
        if len(args) == 2:
            name, phone = args
        else:
            name, phone = _prompt_name_and_phone()

        ok = add_friend_by_contact(name, phone)
        return 0 if ok else 1
    except KakaoWinError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
