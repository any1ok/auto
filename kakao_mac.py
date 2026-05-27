"""카카오톡 자동화 (macOS 전용).

Step 1 — 이미 실행 중인 카카오톡 창을 frontmost 로
Step 2 — ⌘+1(친구) / ⌘+2(채팅) 탭 포커스
Step 3 — 현재 탭 상단 검색창에 텍스트 입력 (Enter 안 누름)
Step 4 — 검색 결과의 첫 데이터 row 이름이 query 와 같은지 확인 (일치 시 row 인덱스 반환)
Step 5 — Step 4 가 알려준 row 인덱스만큼 ↓ 누른 뒤 Return 으로 열기
Step 6 — 카카오톡 windows 중 AXTitle == query 인 윈도우가 떴는지로 열림 검증
Step 7 — 열린 채팅방에 메시지를 ⌘V 로 붙여넣고 Return 으로 전송
Step 8 — 열린 채팅방에 이미지/파일을 파일 선택창 + Return 으로 전송
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


KAKAO_APP_NAME = "KakaoTalk"
KAKAO_MAIN_WINDOW_TITLES = ("카카오톡", "KakaoTalk")
TAB_FRIENDS = "1"
TAB_CHATS = "2"

# 한글 IME 가 켜져 있으면 keystroke "f" 가 "ㄹ" 로 번역되므로 단축키는 모두 key code.
KEY_CODE_A = 0
KEY_CODE_F = 3
KEY_CODE_G = 5
KEY_CODE_V = 9
KEY_CODE_RETURN = 36
KEY_CODE_DELETE = 51
KEY_CODE_ESCAPE = 53
KEY_CODE_DOWN = 125

FRONTMOST_TIMEOUT_S = 1.5
FRONTMOST_POLL_INTERVAL_S = 0.04

# Step 4 검색 결과 안정화 대기 (필요하면 머신/네트워크 속도에 맞춰 조정).
# - SEARCH_INITIAL_DELAY_S: paste 직후 카톡이 결과 갱신할 시간 (초기 1회 대기)
# - SEARCH_STABILIZE_INTERVAL_S: 폴링 간격 (각 스냅샷 사이 delay)
# - SEARCH_STABILIZE_MAX_ITERS: 안정화 폴링 최대 반복 횟수 (총 대기 ≈ INTERVAL × ITERS)
SEARCH_INITIAL_DELAY_S = 0.4
SEARCH_STABILIZE_INTERVAL_S = 0.3
SEARCH_STABILIZE_MAX_ITERS = 10

# Step 6 채팅방 윈도우 등장 대기 (Return → 카카오톡이 새 윈도우 띄우는 시간).
OPEN_VERIFY_INITIAL_DELAY_S = 0.3
OPEN_VERIFY_INTERVAL_S = 0.2
OPEN_VERIFY_MAX_ITERS = 15

# Step 8 파일 전송 확인창 대기.
FILE_PICKER_TIMEOUT_S = 5.0
FILE_PICKER_BUTTON_TRY_TIMEOUT_S = 0.8
FILE_SEND_PREVIEW_TIMEOUT_S = 5.0
FILE_SEND_CLOSE_TIMEOUT_S = 5.0
FILE_SEND_POLL_INTERVAL_S = 0.1

class KakaoMacError(Exception):
    """카카오톡 자동화 중 발생하는 오류."""


def _ensure_macos() -> None:
    if platform.system() != "Darwin":
        raise KakaoMacError(f"macOS 전용입니다. 현재 OS: {platform.system()}")


def _run_osascript(script: str) -> str:
    try:
        r = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
    except FileNotFoundError as e:
        raise KakaoMacError("osascript 를 찾을 수 없습니다 (macOS 전용)") from e
    if r.returncode != 0:
        raise KakaoMacError(
            f"osascript 실패 (exit={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    return r.stdout.strip()


def _set_clipboard(text: str) -> None:
    try:
        env = os.environ.copy()
        # Codex 앱 터미널은 LC_ALL=C 인 경우가 있어 pbcopy 가 한글을 비울 수 있다.
        env["LC_ALL"] = "en_US.UTF-8"
        env["LC_CTYPE"] = "en_US.UTF-8"
        r = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"), check=False, env=env
        )
    except FileNotFoundError as e:
        raise KakaoMacError("pbcopy 를 찾을 수 없습니다 (macOS 전용)") from e
    if r.returncode != 0:
        raise KakaoMacError("pbcopy 실행 실패")


def _applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _resolve_existing_file_path(raw_path: str) -> Path:
    """CLI 에서 받은 파일 경로를 실제 macOS 파일로 해석한다."""
    if not raw_path:
        raise KakaoMacError("전송할 파일 경로가 비어 있습니다.")

    raw = Path(raw_path).expanduser()
    script_dir = Path(__file__).resolve().parent
    if raw.is_absolute():
        candidates = [raw]
    else:
        candidates = [Path.cwd() / raw, script_dir / raw]
    candidates.append(script_dir / raw.name)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue

    searched = ", ".join(str(p) for p in candidates)
    raise KakaoMacError(
        f"전송할 파일을 찾지 못했습니다: {raw_path!r}. 확인한 후보: {searched}"
    )


def check_accessibility_permission() -> bool:
    """AXIsProcessTrusted() 로 권한 확인 (AppleScript `UI elements enabled` 는 false positive 가 있어 안 씀)."""
    try:
        lib = ctypes.util.find_library("ApplicationServices")
        if not lib:
            return False
        services = ctypes.cdll.LoadLibrary(lib)
        services.AXIsProcessTrusted.restype = ctypes.c_bool
        services.AXIsProcessTrusted.argtypes = []
        return bool(services.AXIsProcessTrusted())
    except OSError:
        return False


def ensure_accessibility_or_exit() -> None:
    if check_accessibility_permission():
        return
    print(
        "[권한 필요] 접근성(Accessibility) 권한이 없습니다.\n"
        "  시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용 에서\n"
        "  현재 실행 중인 터미널/IDE(또는 python 바이너리)를 추가해주세요.",
        file=sys.stderr,
    )
    subprocess.run(
        [
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ],
        check=False,
    )
    sys.exit(3)


def is_kakao_running() -> bool:
    script = (
        'tell application "System Events" to '
        f'(name of processes) contains "{KAKAO_APP_NAME}"'
    )
    return _run_osascript(script).lower() == "true"


def wait_for_frontmost(
    name: str = KAKAO_APP_NAME,
    timeout_s: float = FRONTMOST_TIMEOUT_S,
    interval_s: float = FRONTMOST_POLL_INTERVAL_S,
) -> bool:
    """activate 직후 sleep 대신 frontmost 프로세스를 폴링."""
    script = (
        'tell application "System Events" to '
        "name of first process whose frontmost is true"
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if _run_osascript(script) == name:
                return True
        except KakaoMacError:
            pass
        time.sleep(interval_s)
    return False


def _activate_kakao() -> None:
    _run_osascript(f'tell application "{KAKAO_APP_NAME}" to activate')
    if not wait_for_frontmost():
        raise KakaoMacError(
            f"카카오톡이 {FRONTMOST_TIMEOUT_S}s 안에 frontmost 가 되지 않았습니다."
        )


def _focus_main_window() -> bool:
    titles = ", ".join(f'"{_applescript_escape(t)}"' for t in KAKAO_MAIN_WINDOW_TITLES)
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set mainTitles to {{{titles}}}
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if mainTitles contains wn then
        perform action "AXRaise" of w
        return "OK"
      end if
    end repeat
    return "NOT_FOUND"
  end tell
end tell"""
    return _run_osascript(script) == "OK"


def step1_activate_kakao() -> None:
    if not is_kakao_running():
        raise KakaoMacError("카카오톡이 실행되어 있지 않습니다. 먼저 카카오톡을 켜주세요.")
    _activate_kakao()
    print("[Step 1] 카카오톡을 포커스했습니다.")


def step2_focus_tab(choice: str) -> None:
    if choice not in (TAB_FRIENDS, TAB_CHATS):
        raise KakaoMacError(f"잘못된 선택: {choice!r} (1=친구, 2=채팅 만 가능)")
    _activate_kakao()
    if not _focus_main_window():
        raise KakaoMacError("카카오톡 메인 창을 찾지 못했습니다.")
    _run_osascript(
        f'tell application "System Events" to tell process "{KAKAO_APP_NAME}" '
        f'to keystroke "{choice}" using command down'
    )
    label = "친구" if choice == TAB_FRIENDS else "채팅"
    print(f"[Step 2] {label} 탭으로 포커스했습니다. (⌘+{choice})")


def step3_search(query: str) -> None:
    """검색창에 query 를 입력. ⌘F → ⌘A → delete → ⌘V batch (Enter 미입력).

    한글은 pbcopy + ⌘V 로 붙여넣어 IME 의 직접 타이핑 변환을 피한다.
    """
    _set_clipboard(query)
    _activate_kakao()
    if not _focus_main_window():
        raise KakaoMacError("카카오톡 메인 창을 찾지 못했습니다.")
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    key code {KEY_CODE_F} using command down
    key code {KEY_CODE_A} using command down
    key code {KEY_CODE_DELETE}
    key code {KEY_CODE_V} using command down
  end tell
end tell"""
    _run_osascript(script)
    print(f"[Step 3] 검색창에 입력 완료: {query!r}")


def step4_check_first_match(query: str) -> Optional[int]:
    """검색 결과의 첫 데이터 row 이름이 query 와 같은지 확인.

    구조 가정: window > scroll area > {outline | table | list} > row > cell > static text.
    채팅 탭은 outline 대신 table/list 인 경우가 있어 셋 다 시도, 그래도 안 잡히면
    window 직속 outline, 최후엔 entire_contents 까지 fallback. 첫 row 는 보통
    카운트 배지("1", "999+") 이므로 건너뛴다.

    반환: 일치 시 첫 데이터 row 의 AX 1-indexed 인덱스 (Step 5 에서 ↓ 누를 횟수),
    불일치/미발견 시 None.

    검색 로딩 대기: paste 직후엔 이전 검색 결과가 잠깐 남아있을 수 있어
    초기 delay + 스냅샷(count|이름|idx) 이 두 번 연속 동일해질 때까지 폴링.
    """
    target = _applescript_escape(query)
    main_titles = ", ".join(
        f'"{_applescript_escape(t)}"' for t in KAKAO_MAIN_WINDOW_TITLES
    )
    script = f"""\
on isCountBadge(s)
  if s is "" then return true
  if (length of s) > 6 then return false
  repeat with i from 1 to length of s
    if "0123456789+" does not contain (text i thru i of s) then return false
  end repeat
  return true
end isCountBadge

tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set mainTitles to {{{main_titles}}}
    set targetWindow to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if mainTitles contains wn then
        set targetWindow to w
        exit repeat
      end if
    end repeat
    if targetWindow is missing value then
      return "NOT_FOUND" & linefeed & "0" & linefeed & "" & linefeed & "no-main-window" & linefeed & "0" & linefeed & "failed"
    end if

    set firstName to ""
    set firstRowIdx to 0
    set rowsInfo to {{}}
    set rowSource to ""

    -- 검색 paste 직후 이전 결과가 남아있을 수 있어 초기 로딩 대기
    delay {SEARCH_INITIAL_DELAY_S}

    set prevSnapshot to "__INIT__"
    set stabIter to 0
    set stabilized to false
    repeat {SEARCH_STABILIZE_MAX_ITERS} times
      set stabIter to stabIter + 1
      set firstName to ""
      set firstRowIdx to 0
      set rowsInfo to {{}}
      set allRows to {{}}
      set rowSource to ""

      -- (1) scroll area > outline > row
      try
        repeat with sa in (scroll areas of targetWindow)
          try
            repeat with o in (outlines of sa)
              try
                repeat with r in (rows of o)
                  copy contents of r to end of allRows
                end repeat
              end try
            end repeat
          end try
        end repeat
        if (count of allRows) > 0 then set rowSource to "sa>outline>row"
      end try

      -- (2) scroll area > table > row
      if (count of allRows) is 0 then
        try
          repeat with sa in (scroll areas of targetWindow)
            try
              repeat with t in (tables of sa)
                try
                  repeat with r in (rows of t)
                    copy contents of r to end of allRows
                  end repeat
                end try
              end repeat
            end try
          end repeat
          if (count of allRows) > 0 then set rowSource to "sa>table>row"
        end try
      end if

      -- (3) scroll area > list > row
      if (count of allRows) is 0 then
        try
          repeat with sa in (scroll areas of targetWindow)
            try
              repeat with lst in (lists of sa)
                try
                  repeat with r in (rows of lst)
                    copy contents of r to end of allRows
                  end repeat
                end try
              end repeat
            end try
          end repeat
          if (count of allRows) > 0 then set rowSource to "sa>list>row"
        end try
      end if

      -- (4) window > outline > row
      if (count of allRows) is 0 then
        try
          repeat with o in (outlines of targetWindow)
            try
              repeat with r in (rows of o)
                copy contents of r to end of allRows
              end repeat
            end try
          end repeat
          if (count of allRows) > 0 then set rowSource to "win>outline>row"
        end try
      end if

      -- (5) 최후 fallback: entire_contents 에서 class==row
      if (count of allRows) is 0 then
        try
          repeat with elem in (entire contents of targetWindow)
            try
              if ((class of (contents of elem)) as text) is "row" then
                copy contents of elem to end of allRows
              end if
            end try
          end repeat
          if (count of allRows) > 0 then set rowSource to "entire_contents>row"
        end try
      end if

      -- row 이름: cell 첫 UI elements 중 first non-empty static text → 없으면 row 전체 트리
      set rc to 0
      repeat with r in allRows
        set rc to rc + 1
        set rowText to ""
        try
          repeat with kid in (UI elements of (first UI element of (contents of r)))
            try
              if ((class of (contents of kid)) as text) is "static text" then
                set v to (value of (contents of kid)) as text
                if v is not "" then
                  set rowText to v
                  exit repeat
                end if
              end if
            end try
          end repeat
        end try
        if rowText is "" then
          try
            repeat with kid in (entire contents of (contents of r))
              try
                if ((class of (contents of kid)) as text) is "static text" then
                  set v to (value of (contents of kid)) as text
                  if v is not "" then
                    set rowText to v
                    exit repeat
                  end if
                end if
              end try
            end repeat
          end try
        end if

        copy ("[row " & rc & "] " & rowText) to end of rowsInfo
        if firstName is "" and not (my isCountBadge(rowText)) then
          set firstName to rowText
          set firstRowIdx to rc
          exit repeat
        end if
      end repeat

      -- 스냅샷 = (전체 row 수)|firstName|firstRowIdx.
      -- 두 번 연속 동일 ⇒ 검색 결과 안정화 완료로 간주.
      set snapshot to ((count of allRows) as text) & "|" & firstName & "|" & (firstRowIdx as text)
      if snapshot is prevSnapshot then
        set stabilized to true
        exit repeat
      end if
      set prevSnapshot to snapshot
      delay {SEARCH_STABILIZE_INTERVAL_S}
    end repeat

    if stabilized then
      set stabStatus to "stable"
    else
      set stabStatus to "timeout"
    end if

    set status to "NOT_FOUND"
    if firstName is not "" then
      if firstName is targetName then
        set status to "MATCH"
      else
        set status to "MISMATCH"
      end if
    end if

    set AppleScript's text item delimiters to linefeed
    set rowsStr to rowsInfo as text
    set AppleScript's text item delimiters to ""
    return status & linefeed & (firstRowIdx as text) & linefeed & firstName & linefeed & rowSource & linefeed & (stabIter as text) & linefeed & stabStatus & linefeed & rowsStr
  end tell
end tell"""

    result = _run_osascript(script)
    lines = result.split("\n")
    status = lines[0] if lines else ""
    try:
        first_idx = int(lines[1]) if len(lines) > 1 else 0
    except ValueError:
        first_idx = 0
    first_name = lines[2] if len(lines) > 2 else ""
    row_source = lines[3] if len(lines) > 3 else ""
    try:
        stab_iter = int(lines[4]) if len(lines) > 4 else 0
    except ValueError:
        stab_iter = 0
    stab_status = lines[5] if len(lines) > 5 else ""
    rows = [ln for ln in lines[6:] if ln]

    print(
        f"[Step 4] 안정화 {stab_status} ({stab_iter}/{SEARCH_STABILIZE_MAX_ITERS} 회 시도) / "
        f"row 수집 path = {row_source or '(none)'} / 첫 데이터 row 까지의 목록:",
        file=sys.stderr,
    )
    if rows:
        prefix = f"[row {first_idx}]"
        for line in rows:
            mark = "  ← 첫 데이터 row" if line.startswith(prefix) else ""
            print(f"  {line}{mark}", file=sys.stderr)
    else:
        print("  (row 가 하나도 안 잡힘)", file=sys.stderr)

    if status == "MATCH":
        print(
            f"[Step 4] 첫 데이터 row '{first_name}' == '{query}' → 일치 "
            f"(AX row 인덱스 = {first_idx})."
        )
        return first_idx

    reasons = {
        "MISMATCH": f"첫 데이터 row '{first_name}' 가 query '{query}' 와 다름",
        "NOT_FOUND": "데이터 row 를 찾지 못했습니다 (검색 결과가 비었거나 모두 카운트 배지)",
    }
    print(f"[Step 4] {reasons.get(status, f'알 수 없는 상태: {status!r}')}", file=sys.stderr)
    return None


def step5_open_chatroom(first_idx: int) -> None:
    """Step 4 가 찾은 첫 데이터 row 를 키보드로 연다.

    카카오톡 Mac 검색창은 입력 직후 첫 결과를 자동 하이라이트하지 않으므로
    Return 만 보내면 무시된다. 검색창에서 ↓ 를 누를 때마다 결과 리스트의
    다음 row 로 포커스가 이동하므로, Step 4 가 알려준 1-indexed `first_idx`
    만큼 ↓ 를 보낸 뒤 Return 하면 매칭 row 가 열린다. (배지 row "1"/"999+"
    도 키보드 navigable 이므로 first_idx 가 그대로 ↓ 횟수와 같음.)

    Step 3 와 같은 batch 패턴: 모든 키 코드를 단일 osascript 안에서 전송 →
    중간에 터미널로 포커스가 빠질 여지 없음.
    """
    if first_idx < 1:
        raise KakaoMacError(f"step5: 잘못된 first_idx={first_idx} (>= 1 이어야 함)")
    _activate_kakao()
    if not _focus_main_window():
        raise KakaoMacError("카카오톡 메인 창을 찾지 못했습니다.")
    down_lines = "\n    ".join(
        f"key code {KEY_CODE_DOWN}" for _ in range(first_idx)
    )
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    {down_lines}
    key code {KEY_CODE_RETURN}
  end tell
end tell"""
    _run_osascript(script)
    print(f"[Step 5] ↓ × {first_idx} → Return 으로 채팅방을 열었습니다.")


def step6_verify_chatroom_opened(query: str) -> bool:
    """Step 5 후 query 채팅방이 실제로 열렸는지 AX 윈도우 타이틀로 검증.

    카카오톡 Mac 은 채팅방을 별도 윈도우로 띄우므로 KakaoTalk 프로세스의
    windows 중 name(=AXTitle) 이 query 와 (a) 정확히 같거나 (b) query 를
    포함하면 열린 것으로 본다. (b) 는 카톡이 타이틀에 인원수/장식 문자열을
    덧붙이는 경우 대비.

    UI 렌더 지연 대비 초기 delay + 폴링. 진단 가독성을 위해 매 회 모든
    윈도우 이름을 함께 수집해 마지막 시도의 목록을 stderr 로 찍는다.
    """
    target = _applescript_escape(query)
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set evidence to "NONE"
    set winNames to {{}}
    set i to 0

    delay {OPEN_VERIFY_INITIAL_DELAY_S}

    repeat {OPEN_VERIFY_MAX_ITERS} times
      set i to i + 1
      set evidence to "NONE"
      set winNames to {{}}
      try
        repeat with w in windows
          set wn to ""
          try
            set wn to name of w
          end try
          if wn is missing value then set wn to ""
          if wn is not "" then copy wn to end of winNames
          if wn is targetName then
            set evidence to "WINDOW_TITLE_EXACT"
            exit repeat
          else if wn contains targetName then
            -- 더 강한 EXACT 증거가 나올 수 있으니 break 하지 않고 계속.
            if evidence is "NONE" then set evidence to "WINDOW_TITLE_CONTAINS"
          end if
        end repeat
      end try
      if evidence is "WINDOW_TITLE_EXACT" then exit repeat
      delay {OPEN_VERIFY_INTERVAL_S}
    end repeat

    set AppleScript's text item delimiters to "|"
    set wlist to (winNames as text)
    set AppleScript's text item delimiters to ""
    return evidence & linefeed & (i as text) & linefeed & wlist
  end tell
end tell"""

    result = _run_osascript(script)
    lines = result.split("\n")
    evidence = lines[0] if lines else "NONE"
    try:
        iters = int(lines[1]) if len(lines) > 1 else 0
    except ValueError:
        iters = 0
    win_list_str = lines[2] if len(lines) > 2 else ""
    win_names = [n for n in win_list_str.split("|") if n]

    print(
        f"[Step 6] 검증 {iters}/{OPEN_VERIFY_MAX_ITERS} 회 시도 / 현재 카카오톡 윈도우 목록:",
        file=sys.stderr,
    )
    if win_names:
        for n in win_names:
            mark = "  ← 매치" if n == query or query in n else ""
            print(f"  - {n!r}{mark}", file=sys.stderr)
    else:
        print("  (윈도우가 하나도 안 잡힘)", file=sys.stderr)

    if evidence == "WINDOW_TITLE_EXACT":
        print(f"[Step 6] '{query}' 윈도우 발견 (정확 일치) → 채팅방 열림 확인.")
        return True
    if evidence == "WINDOW_TITLE_CONTAINS":
        print(
            f"[Step 6] query 를 포함한 윈도우 발견 → 채팅방 열림으로 간주 "
            f"(타이틀 장식 가능성)."
        )
        return True

    print(
        f"[Step 6] '{query}' 채팅방 윈도우를 못 찾았습니다. "
        f"인라인 패널 방식으로 열렸거나 Step 5 가 실패했을 수 있습니다.",
        file=sys.stderr,
    )
    return False


def step7_send_message(message: str) -> None:
    """열린 채팅방에 message 를 ⌘V 로 붙여넣고 Return 으로 전송.

    Step 6 가 채팅방 윈도우 열림을 확인했으므로 카톡이 그 윈도우의 메시지
    입력칸에 자동 포커스해 둔 상태. Step 3 와 100% 동일한 패턴:
      - pbcopy + ⌘V 로 한글/이모지/특수문자/긴 텍스트 안전 (직접 타이핑 X)
      - keystroke 가 아닌 key code 만 사용 → 한글 IME 영향 0
      - 붙여넣기 + 전송을 단일 osascript 안에서 batch 전송

    전제: 카톡 환경설정에서 'Return = 보내기' 기본값 유지. 'Return = 줄바꿈'
    으로 바꿔놨다면 이 step 은 메시지를 보내지 않고 줄만 바꾼다.
    """
    if not message:
        raise KakaoMacError("step7: 보낼 메시지가 비어 있습니다.")
    _set_clipboard(message)
    _activate_kakao()
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    key code {KEY_CODE_V} using command down
    key code {KEY_CODE_RETURN}
  end tell
end tell"""
    _run_osascript(script)
    preview = message if len(message) <= 60 else message[:57] + "..."
    print(f"[Step 7] 메시지 전송 완료: {preview!r}")


def _focus_chat_window(chat_title: str) -> None:
    """열린 채팅창을 AXRaise 로 앞으로 가져온다. 마우스/버튼 클릭은 쓰지 않는다."""
    target = _applescript_escape(chat_title)
    _activate_kakao()
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set targetWin to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if wn is targetName then
        set targetWin to w
        exit repeat
      else if targetWin is missing value and wn contains targetName then
        set targetWin to w
      end if
    end repeat
    if targetWin is missing value then return "NOT_FOUND"
    perform action "AXRaise" of targetWin
    return "OK"
  end tell
end tell"""
    result = _run_osascript(script)
    if result != "OK":
        raise KakaoMacError(f"채팅창을 앞으로 가져오지 못했습니다: {chat_title!r}")


def _file_send_sheet_status(chat_title: str) -> tuple[str, str, str]:
    """파일 전송 확인 sheet 상태를 읽는다."""
    target = _applescript_escape(chat_title)
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set targetWin to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if wn is targetName then
        set targetWin to w
        exit repeat
      else if targetWin is missing value and wn contains targetName then
        set targetWin to w
      end if
    end repeat
    if targetWin is missing value then return "NO_CHAT_WINDOW" & linefeed & "" & linefeed & ""

    set collectedTexts to {{}}
    try
      repeat with sh in sheets of targetWin
        set sendButtonName to ""
        repeat with b in buttons of sh
          set bn to ""
          try
            set bn to name of b as text
          end try
          if bn contains "전송" then set sendButtonName to bn
        end repeat
        repeat with t in static texts of sh
          set tv to ""
          try
            set tv to value of t as text
          end try
          if tv is not "" then copy tv to end of collectedTexts
        end repeat
        if sendButtonName is not "" then
          set AppleScript's text item delimiters to " | "
          set textJoined to collectedTexts as text
          set AppleScript's text item delimiters to ""
          return "FOUND" & linefeed & sendButtonName & linefeed & textJoined
        end if
      end repeat
    end try

    set AppleScript's text item delimiters to " | "
    set textJoined to collectedTexts as text
    set AppleScript's text item delimiters to ""
    if textJoined is "" then
      return "NONE" & linefeed & "" & linefeed & ""
    end if
    return "SHEET_OTHER" & linefeed & "" & linefeed & textJoined
  end tell
end tell"""
    result = _run_osascript(script)
    lines = result.split("\n", 2)
    status = lines[0] if lines else ""
    button = lines[1] if len(lines) > 1 else ""
    details = lines[2] if len(lines) > 2 else ""
    return status, button, details


def _file_picker_sheet_status(chat_title: str) -> tuple[str, str]:
    """카카오톡 첨부 파일 선택 sheet 상태를 읽는다."""
    target = _applescript_escape(chat_title)
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set targetWin to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if wn is targetName then
        set targetWin to w
        exit repeat
      else if targetWin is missing value and wn contains targetName then
        set targetWin to w
      end if
    end repeat
    if targetWin is missing value then return "NO_CHAT_WINDOW" & linefeed & ""

    set buttonNames to {{}}
    try
      repeat with sh in sheets of targetWin
        repeat with b in buttons of sh
          set bn to ""
          try
            set bn to name of b as text
          end try
          if bn is not "" then copy bn to end of buttonNames
          if bn is "열기" or bn is "Open" then
            return "FOUND" & linefeed & bn
          end if
        end repeat
      end repeat
    end try

    set AppleScript's text item delimiters to " | "
    set buttonsJoined to buttonNames as text
    set AppleScript's text item delimiters to ""
    if buttonsJoined is "" then
      return "NONE" & linefeed & ""
    end if
    return "SHEET_OTHER" & linefeed & buttonsJoined
  end tell
end tell"""
    result = _run_osascript(script)
    lines = result.split("\n", 1)
    status = lines[0] if lines else ""
    details = lines[1] if len(lines) > 1 else ""
    return status, details


def _wait_for_file_send_sheet(chat_title: str) -> str:
    deadline = time.monotonic() + FILE_SEND_PREVIEW_TIMEOUT_S
    last_status = ""
    last_details = ""
    while time.monotonic() < deadline:
        status, send_button, details = _file_send_sheet_status(chat_title)
        last_status = status
        last_details = details
        if status == "FOUND":
            return send_button
        time.sleep(FILE_SEND_POLL_INTERVAL_S)
    raise KakaoMacError(
        "파일 붙여넣기 후 카카오톡 '파일 전송' 확인창을 찾지 못했습니다. "
        f"마지막 상태={last_status!r}, 화면 문구={last_details!r}"
    )


def _wait_for_file_picker_sheet(
    chat_title: str,
    timeout_s: float = FILE_PICKER_TIMEOUT_S,
    *,
    raise_on_timeout: bool = True,
) -> Optional[str]:
    deadline = time.monotonic() + timeout_s
    last_status = ""
    last_details = ""
    while time.monotonic() < deadline:
        status, details = _file_picker_sheet_status(chat_title)
        last_status = status
        last_details = details
        if status == "FOUND":
            return details
        time.sleep(FILE_SEND_POLL_INTERVAL_S)
    if not raise_on_timeout:
        return None
    raise KakaoMacError(
        "첨부 파일 선택창을 찾지 못했습니다. "
        f"마지막 상태={last_status!r}, 버튼={last_details!r}"
    )


def _wait_for_file_send_sheet_closed(chat_title: str) -> None:
    deadline = time.monotonic() + FILE_SEND_CLOSE_TIMEOUT_S
    last_status = ""
    last_details = ""
    while time.monotonic() < deadline:
        status, _send_button, details = _file_send_sheet_status(chat_title)
        last_status = status
        last_details = details
        if status in ("NONE", "NO_CHAT_WINDOW"):
            return
        time.sleep(FILE_SEND_POLL_INTERVAL_S)
    raise KakaoMacError(
        "Return 전송 후 카카오톡 '파일 전송' 확인창이 닫히지 않았습니다. "
        f"마지막 상태={last_status!r}, 화면 문구={last_details!r}"
    )


def _chat_window_button_snapshot(chat_title: str) -> list[dict[str, object]]:
    """채팅창 top-level 버튼의 AX index/좌표를 읽는다."""
    target = _applescript_escape(chat_title)
    script = f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set targetWin to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if wn is targetName then
        set targetWin to w
        exit repeat
      else if targetWin is missing value and wn contains targetName then
        set targetWin to w
      end if
    end repeat
    if targetWin is missing value then return ""

    set rowsOut to {{}}
    set idx to 0
    repeat with b in buttons of targetWin
      set idx to idx + 1
      set nm to ""
      set descText to ""
      set x to 0
      set y to 0
      set w to 0
      set h to 0
      try
        set nm to name of b as text
        if nm is "missing value" then set nm to ""
      end try
      try
        set descText to description of b as text
        if descText is "missing value" then set descText to ""
      end try
      try
        set p to position of b
        set x to item 1 of p
        set y to item 2 of p
      end try
      try
        set s to size of b
        set w to item 1 of s
        set h to item 2 of s
      end try
      copy ((idx as text) & "|" & (x as text) & "|" & (y as text) & "|" & (w as text) & "|" & (h as text) & "|" & nm & "|" & descText) to end of rowsOut
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to rowsOut as text
    set AppleScript's text item delimiters to ""
    return joined
  end tell
end tell"""
    result = _run_osascript(script)
    buttons: list[dict[str, object]] = []
    for line in result.splitlines():
        parts = line.split("|", 6)
        if len(parts) != 7:
            continue
        try:
            idx, x, y, width, height = (int(parts[i]) for i in range(5))
        except ValueError:
            continue
        buttons.append(
            {
                "idx": idx,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "name": parts[5],
                "desc": parts[6],
            }
        )
    return buttons


def _file_picker_button_candidates(chat_title: str) -> list[dict[str, object]]:
    """하단 툴바에서 파일 첨부 버튼 후보를 우선순위 순서로 반환한다."""
    buttons = _chat_window_button_snapshot(chat_title)
    if not buttons:
        raise KakaoMacError("채팅창 버튼 목록을 읽지 못했습니다.")

    max_y = max(int(button["y"]) for button in buttons)
    toolbar = [
        button
        for button in buttons
        if max_y - int(button["y"]) <= 24
        and int(button["width"]) <= 44
        and int(button["height"]) <= 44
        and str(button["name"]) not in {"전송", "취소", "열기", "Open"}
        and "닫기" not in str(button["desc"])
        and "최소화" not in str(button["desc"])
        and "확대" not in str(button["desc"])
    ]
    toolbar.sort(key=lambda button: int(button["x"]))
    if not toolbar:
        snapshot = ", ".join(
            f"#{button['idx']}({button['x']},{button['y']},{button['width']}x{button['height']},{button['name']!r},{button['desc']!r})"
            for button in buttons
        )
        raise KakaoMacError(f"하단 첨부 툴바 버튼 후보를 찾지 못했습니다: {snapshot}")

    preferred_zero_based = 3
    toolbar_with_rank = list(enumerate(toolbar))
    toolbar_with_rank.sort(
        key=lambda item: (
            abs(item[0] - preferred_zero_based),
            0 if item[0] >= preferred_zero_based else 1,
        )
    )
    return [button for _rank, button in toolbar_with_rank]


def _press_chat_button(chat_title: str, button_index: int) -> None:
    target = _applescript_escape(chat_title)
    _run_osascript(
        f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set targetWin to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if wn is targetName then
        set targetWin to w
        exit repeat
      else if targetWin is missing value and wn contains targetName then
        set targetWin to w
      end if
    end repeat
    if targetWin is missing value then error "chat window not found"
    perform action "AXPress" of button {button_index} of targetWin
  end tell
end tell"""
    )


def _cancel_chat_sheet(chat_title: str) -> None:
    """열린 sheet 가 있으면 취소로 닫는다. 전송 버튼은 누르지 않는다."""
    target = _applescript_escape(chat_title)
    _run_osascript(
        f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    set targetName to "{target}"
    set targetWin to missing value
    repeat with w in windows
      set wn to ""
      try
        set wn to name of w as text
      end try
      if wn is targetName then
        set targetWin to w
        exit repeat
      else if targetWin is missing value and wn contains targetName then
        set targetWin to w
      end if
    end repeat
    if targetWin is missing value then return
    repeat with sh in sheets of targetWin
      try
        perform action "AXPress" of button "취소" of sh
        return
      end try
      try
        perform action "AXPress" of button "Cancel" of sh
        return
      end try
    end repeat
    key code {KEY_CODE_ESCAPE}
  end tell
end tell"""
    )


def _open_file_picker_sheet(chat_title: str) -> str:
    """첨부 파일 버튼을 눌러 파일 선택 sheet 를 연다. 실제 전송은 하지 않는다."""
    _focus_chat_window(chat_title)
    already_open = _wait_for_file_picker_sheet(
        chat_title, timeout_s=0.2, raise_on_timeout=False
    )
    if already_open is not None:
        return already_open

    candidates = _file_picker_button_candidates(chat_title)
    tried: list[str] = []
    for button in candidates:
        idx = int(button["idx"])
        tried.append(
            f"#{idx}@({button['x']},{button['y']},{button['width']}x{button['height']})"
        )
        _press_chat_button(chat_title, idx)
        opened = _wait_for_file_picker_sheet(
            chat_title,
            timeout_s=FILE_PICKER_BUTTON_TRY_TIMEOUT_S,
            raise_on_timeout=False,
        )
        if opened is not None:
            return opened
        status, _details = _file_picker_sheet_status(chat_title)
        if status == "SHEET_OTHER":
            _cancel_chat_sheet(chat_title)

    raise KakaoMacError(
        "하단 첨부 버튼 후보를 눌렀지만 파일 선택창이 열리지 않았습니다. "
        f"시도한 버튼={', '.join(tried)}"
    )


def _send_file_via_picker(chat_title: str, path: Path) -> str:
    """이미지/일반 파일 공통 경로. 파일 선택창은 열지만 전송 확정은 Return 만 쓴다."""
    open_button = _open_file_picker_sheet(chat_title)
    _set_clipboard(str(path))
    _run_osascript(
        f"""\
tell application "System Events"
  tell process "{KAKAO_APP_NAME}"
    key code {KEY_CODE_G} using {{command down, shift down}}
    delay 0.2
    key code {KEY_CODE_A} using command down
    delay 0.05
    key code {KEY_CODE_V} using command down
    delay 0.3
    key code {KEY_CODE_RETURN}
    delay 0.7
    key code {KEY_CODE_RETURN}
  end tell
end tell"""
    )
    send_button = _wait_for_file_send_sheet(chat_title)
    _run_osascript(
        f'tell application "System Events" to tell process "{KAKAO_APP_NAME}" '
        f"to key code {KEY_CODE_RETURN}"
    )
    _wait_for_file_send_sheet_closed(chat_title)
    return f"file-picker/{open_button}/{send_button}"


def step8_send_file(chat_title: str, file_path: str) -> None:
    """열린 채팅방에 이미지/파일 1개를 전송한다.

    검증된 흐름:
      - 이미지/일반 파일 모두 첨부 파일 선택창을 열어 경로를 선택한다.
      - 실제 전송 확정은 클릭이 아니라 Return 으로만 한다.
    """
    path = _resolve_existing_file_path(str(file_path))
    method = _send_file_via_picker(chat_title, path)
    print(
        f"[Step 8] 파일 전송 완료: {path} ({path.stat().st_size} bytes, 방식={method!r})"
    )


def step8_send_files(chat_title: str, file_paths: list[str]) -> None:
    """열린 채팅방에 파일 여러 개를 순서대로 전송한다."""
    for idx, raw_path in enumerate(file_paths, 1):
        print(f"[Step 8] 파일 {idx}/{len(file_paths)} 전송 시작: {raw_path}")
        step8_send_file(chat_title, raw_path)


def _prompt_tab() -> str:
    while True:
        raw = input("어디로 포커스할까요? [1] 친구  [2] 채팅 : ").strip()
        if raw in (TAB_FRIENDS, TAB_CHATS):
            return raw
        print("1 또는 2 만 입력해주세요.")


def _prompt_send_kind() -> str:
    while True:
        raw = input("무엇을 보낼까요? [1] 메시지  [2] 파일/이미지 : ").strip()
        if raw in ("1", "2"):
            return raw
        print("1 또는 2 중 하나만 입력해주세요.")


def _split_file_input(raw: str) -> list[str]:
    """파일 prompt 입력을 경로 목록으로 바꾼다."""
    text = raw.strip()
    if not text:
        return []
    separator = ";" if ";" in text else "," if "," in text else None
    if separator is None:
        parts = [text]
    else:
        parts = [part.strip() for part in text.split(separator)]
    return [part.strip('"') for part in parts if part.strip('"')]


def _prompt_file_paths() -> list[str]:
    while True:
        raw = input(
            "보낼 파일/이미지 경로를 입력하세요 (예: a.png, 비우면 생략): "
        ).rstrip("\r\n")
        paths = _split_file_input(raw)
        if paths or not raw.strip():
            return paths
        print("파일 경로를 입력해주세요.")


def _print_usage() -> None:
    print(
        f"사용법: python3 {sys.argv[0]} [1|2] [\"검색어\"] [\"메시지\"] "
        "[--file 파일경로 ...]\n"
        "  1 = 친구, 2 = 채팅\n"
        "  예) python3 kakao_mac.py 2\n"
        "      python3 kakao_mac.py 2 \"홍길동\"\n"
        "      python3 kakao_mac.py 2 \"홍길동\" \"안녕하세요\"\n"
        "      python3 kakao_mac.py 2 \"홍길동\" --file a.png --file Lunching.pdf\n"
        "  --file 이 있으면 메시지 prompt 없이 파일만 전송할 수 있습니다.\n"
        "  메시지를 빈 문자열로 주면(\"\") Step 7 생략.",
        file=sys.stderr,
    )


def _parse_cli_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """기존 positional CLI 를 유지하면서 --file 옵션만 추가 파싱."""
    positional: list[str] = []
    file_paths: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--file":
            i += 1
            if i >= len(argv) or not argv[i]:
                raise ValueError("--file 뒤에는 파일 경로가 필요합니다.")
            file_paths.append(argv[i])
        elif arg.startswith("--file="):
            value = arg.split("=", 1)[1]
            if not value:
                raise ValueError("--file= 뒤에는 파일 경로가 필요합니다.")
            file_paths.append(value)
        elif arg == "--files":
            i += 1
            start = i
            while i < len(argv) and not argv[i].startswith("--"):
                if argv[i]:
                    file_paths.append(argv[i])
                i += 1
            if i == start:
                raise ValueError("--files 뒤에는 하나 이상의 파일 경로가 필요합니다.")
            continue
        elif arg.startswith("--"):
            raise ValueError(f"알 수 없는 옵션: {arg}")
        else:
            positional.append(arg)
        i += 1
    return positional, file_paths


def main() -> int:
    _ensure_macos()

    try:
        args, file_paths = _parse_cli_args(sys.argv[1:])
    except ValueError as e:
        print(f"[오류] {e}", file=sys.stderr)
        _print_usage()
        return 2

    tab: str | None = None
    query: str | None = None
    message: str | None = None
    query_arg_given = False
    message_arg_given = False
    if args:
        if args[0] not in (TAB_FRIENDS, TAB_CHATS):
            _print_usage()
            return 2
        tab = args[0]
    if len(args) >= 2:
        query = args[1]
        query_arg_given = True
    if len(args) >= 3:
        message = args[2]
        message_arg_given = True
    if len(args) > 3:
        print(f"[오류] 위치 인자가 너무 많습니다: {args[3:]}", file=sys.stderr)
        _print_usage()
        return 2

    ensure_accessibility_or_exit()

    # 모든 input() 은 단계 시작 전에. 중간에 받으면 터미널로 포커스 빠져서 키 입력이 새는다.
    if tab is None:
        tab = _prompt_tab()
    if query is None:
        query = input("검색창에 입력할 텍스트: ").rstrip("\n")
    if message is None and not message_arg_given:
        if query_arg_given or file_paths:
            message = ""
        else:
            send_kind = _prompt_send_kind()
            if send_kind == "1":
                message = input("보낼 메시지 (빈 줄이면 안 보냄): ").rstrip("\n")
            else:
                message = ""
                file_paths = _prompt_file_paths()

    try:
        step1_activate_kakao()
        step2_focus_tab(tab)
        step3_search(query)
        first_idx = step4_check_first_match(query)
        if first_idx is not None:
            step5_open_chatroom(first_idx)
            if step6_verify_chatroom_opened(query):
                if message:
                    step7_send_message(message)
                if file_paths:
                    step8_send_files(query, file_paths)
    except KakaoMacError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
