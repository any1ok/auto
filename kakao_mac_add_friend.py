"""카카오톡 친구추가 자동화 진입점 (macOS 전용).

현재 구현 범위:
Step 1 — 접근성 권한 확인 후 이미 실행 중인 카카오톡을 frontmost 로
Step 2 — 기존 macOS 카카오톡 단축키인 Command+1 로 친구 탭 포커스
Step 3 — 친구추가 팝오버 열기 (마우스 좌표 클릭 없이 AXPress)
Step 4 — 연락처 추가 화면에서 이름/전화번호 입력
Step 5 — 친구 추가 확정 후 팝오버 닫힘/오류 문구로 결과 판정
"""

from __future__ import annotations

import sys

from kakao_mac import (
    KEY_CODE_A,
    KEY_CODE_DELETE,
    KEY_CODE_V,
    KakaoMacError,
    TAB_FRIENDS,
    _activate_kakao,
    _applescript_escape,
    _ensure_macos,
    _run_osascript,
    ensure_accessibility_or_exit,
    step1_activate_kakao,
    step2_focus_tab,
)


FRIEND_ADD_RESULT_SUCCESS = "SUCCESS_CLOSED"
FRIEND_ADD_RESULT_SUCCESS_MESSAGE = "SUCCESS_MESSAGE"
FRIEND_ADD_RESULT_ERROR = "ERROR"

FRIEND_ADD_APPLESCRIPT_HELPERS = """\
on _textOf(v)
  try
    if v is missing value then return ""
    return v as text
  on error
    return ""
  end try
end _textOf

on _findFriendAddPopover()
  tell application "System Events"
    tell process "KakaoTalk"
      repeat with elem in UI elements of window 1
        try
          if ((class of elem) as text) is "button" then
            repeat with child in UI elements of elem
              try
                if ((class of child) as text) is "pop over" then return child
              end try
            end repeat
          end if
        end try
      end repeat
    end tell
  end tell
  return missing value
end _findFriendAddPopover

on _isFriendAddPopover(targetPopover)
  if targetPopover is missing value then return false

  set hasTitle to false
  set hasContactTab to false
  set hasIdTab to false
  set hasSubmitButton to false

  tell application "System Events"
    try
      repeat with popChild in UI elements of targetPopover
        set labelText to (my _textOf(name of popChild)) & "\n" & (my _textOf(value of popChild))
        if labelText contains "친구 추가" then
          set hasTitle to true
          try
            if ((class of popChild) as text) is "button" then set hasSubmitButton to true
          end try
        end if
        if labelText contains "연락처" then set hasContactTab to true
        if labelText contains "ID" then set hasIdTab to true
      end repeat
    end try
  end tell

  return hasTitle and hasContactTab and hasIdTab and hasSubmitButton
end _isFriendAddPopover

on _hasFriendAddPopover()
  return my _isFriendAddPopover(my _findFriendAddPopover())
end _hasFriendAddPopover

on _collectTexts(targetPopover)
  set messages to {}
  tell application "System Events"
    try
      repeat with popChild in UI elements of targetPopover
        try
          set cls to (class of popChild) as text
          if cls is "static text" or cls is "button" or cls is "text field" then
            set nm to my _textOf(name of popChild)
            set valText to my _textOf(value of popChild)
            if nm is not "" then copy nm to end of messages
            if valText is not "" and valText is not nm then copy valText to end of messages
          end if
        end try
      end repeat
    end try
  end tell
  set AppleScript's text item delimiters to " | "
  set messagesText to messages as text
  set AppleScript's text item delimiters to ""
  return messagesText
end _collectTexts

on _hasErrorText(messagesText)
  if messagesText contains "할 수 없습니다" then return true
  if messagesText contains "오류" then return true
  if messagesText contains "실패" then return true
  if messagesText contains "없는 번호" then return true
  return false
end _hasErrorText

on _hasSuccessText(messagesText)
  if messagesText contains "친구 등록이 완료되었습니다" then return true
  if messagesText contains "등록이 완료" then return true
  if messagesText contains "추가되었습니다" then return true
  if messagesText contains "이미 등록된 친구" then return true
  if messagesText contains "이미 등록" then return true
  return false
end _hasSuccessText

on _closeFriendAddPopover()
  tell application "System Events" to tell process "KakaoTalk" to key code 53
  delay 0.1
end _closeFriendAddPopover

"""


def step2_focus_friends_tab() -> None:
    """친구추가의 시작점인 친구 탭으로 이동."""
    step2_focus_tab(TAB_FRIENDS)


def step3_open_friend_add_popover() -> None:
    """친구 탭 오른쪽 상단 친구추가 팝오버를 연다.

    카카오톡 Mac 에는 친구추가 공식 단축키가 없으므로, 친구 탭 header 의
    36x36 아이콘 버튼 중 가장 오른쪽(사람+ 아이콘)을 접근성 트리에서 찾아
    AXPress 한다. 마우스 좌표 이동/클릭은 사용하지 않는다.
    """
    _activate_kakao()
    script = FRIEND_ADD_APPLESCRIPT_HELPERS + """\
tell application "System Events"
  tell process "KakaoTalk"
    set targetButton to missing value
    set bestX to -1

    repeat with elem in UI elements of window 1
      try
        if ((class of elem) as text) is "button" then
          set elemSize to size of elem
          set elemPosition to position of elem
          set elemWidth to item 1 of elemSize
          set elemHeight to item 2 of elemSize
          set elemX to item 1 of elemPosition

          -- 친구 탭 header 의 검색/친구추가 아이콘은 둘 다 36x36 버튼이다.
          -- 그중 x 좌표가 더 큰 오른쪽 버튼이 친구추가(사람+) 버튼이다.
          if elemWidth is greater than or equal to 30 and elemWidth is less than or equal to 48 and elemHeight is greater than or equal to 30 and elemHeight is less than or equal to 48 then
            if elemX > bestX then
              set bestX to elemX
              set targetButton to elem
            end if
          end if
        end if
      end try
    end repeat

    if targetButton is missing value then
      return "BUTTON_NOT_FOUND"
    end if

    if my _hasFriendAddPopover() then
      return "ALREADY_OPEN"
    end if

    perform action "AXPress" of targetButton

    repeat 10 times
      delay 0.1
      if my _hasFriendAddPopover() then
        return "OPENED"
      end if
    end repeat

    return "NOT_OPENED"
  end tell
end tell"""

    result = _run_osascript(script)
    if result not in {"OPENED", "ALREADY_OPEN"}:
        raise KakaoMacError(
            "친구추가 팝오버를 열지 못했습니다. "
            f"상태={result!r}. 카카오톡 UI 구조가 바뀌었을 수 있습니다."
        )

    suffix = "이미 열려 있음" if result == "ALREADY_OPEN" else "AXPress"
    print(f"[Step 3] 친구추가 팝오버를 열었습니다. ({suffix})")


def step4_fill_contact_fields(name: str, phone: str) -> None:
    """연락처 탭의 이름/전화번호 필드를 채운다.

    `set value` 는 값만 바꾸고 카카오톡 내부 validation 이벤트를 발생시키지 않아
    버튼이 비활성으로 남는다. 그래서 각 필드에 AX focus 를 준 뒤 클립보드 붙여넣기로
    입력한다.

    `친구 추가` 버튼 활성 여부는 로그로 남기고, 실제 확정/실패 판정은 Step 5 가 맡는다.
    """
    if not name.strip():
        raise KakaoMacError("step4: 이름이 비어 있습니다.")
    if not phone.strip():
        raise KakaoMacError("step4: 전화번호가 비어 있습니다.")

    name_escaped = _applescript_escape(name)
    phone_escaped = _applescript_escape(phone)
    _activate_kakao()
    script = FRIEND_ADD_APPLESCRIPT_HELPERS + f"""\
tell application "System Events"
  tell process "KakaoTalk"
    set targetPopover to my _findFriendAddPopover()

    if targetPopover is missing value then
      return "POPOVER_NOT_FOUND"
    end if

    set focused of text field 1 of targetPopover to true
    delay 0.1
    key code {KEY_CODE_A} using command down
    key code {KEY_CODE_DELETE}
    delay 0.05
    set the clipboard to "{name_escaped}"
    key code {KEY_CODE_V} using command down
    delay 0.2

    set focused of text field 2 of targetPopover to true
    delay 0.1
    key code {KEY_CODE_A} using command down
    key code {KEY_CODE_DELETE}
    delay 0.05
    set the clipboard to "{phone_escaped}"
    key code {KEY_CODE_V} using command down
    delay 0.5

    set actualName to (value of text field 1 of targetPopover) as text
    set actualPhone to (value of text field 2 of targetPopover) as text
    set submitEnabled to enabled of button "친구 추가" of targetPopover

    return "OK" & linefeed & actualName & linefeed & actualPhone & linefeed & (submitEnabled as text)
  end tell
end tell"""

    result = _run_osascript(script)
    lines = result.split("\n")
    status = lines[0] if lines else ""
    if status != "OK":
        raise KakaoMacError(
            "친구추가 연락처 입력 필드를 찾지 못했습니다. "
            f"상태={status!r}. 카카오톡 UI 구조가 바뀌었을 수 있습니다."
        )

    actual_name = lines[1] if len(lines) > 1 else ""
    actual_phone = lines[2] if len(lines) > 2 else ""
    submit_enabled = (lines[3].lower() == "true") if len(lines) > 3 else False
    state = "활성" if submit_enabled else "비활성"
    print(
        f"[Step 4] 이름/전화번호 입력 완료: name={actual_name!r}, "
        f"phone={actual_phone!r}, 친구 추가 버튼={state}"
    )


def step5_confirm_friend_add() -> bool:
    """친구 추가를 확정하고 결과를 판정한다.

    성공은 친구추가 팝오버가 닫히거나 `친구 등록이 완료되었습니다.` 문구가
    노출되는 것으로 판정한다. 실패는 팝오버가 유지된 채 `할 수 없습니다` 같은
    오류 문구가 노출되는지로 판정하고, 판정 후 팝오버를 ESC 로 닫는다.
    """
    _activate_kakao()
    script = FRIEND_ADD_APPLESCRIPT_HELPERS + """\
tell application "System Events"
  tell process "KakaoTalk"
    set targetPopover to my _findFriendAddPopover()
    if targetPopover is missing value then return "POPOVER_NOT_FOUND" & linefeed & ""

    set submitButton to missing value
    try
      set submitButton to button "친구 추가" of targetPopover
    end try
    if submitButton is missing value then
      set messagesText to my _collectTexts(targetPopover)
      my _closeFriendAddPopover()
      return "SUBMIT_NOT_FOUND" & linefeed & messagesText
    end if
    if not (enabled of submitButton) then
      set messagesText to my _collectTexts(targetPopover)
      my _closeFriendAddPopover()
      return "BUTTON_DISABLED" & linefeed & messagesText
    end if

    perform action "AXPress" of submitButton
  end tell
end tell

repeat 30 times
  delay 0.2
  set targetPopover to my _findFriendAddPopover()
  if targetPopover is missing value then
    return "SUCCESS_CLOSED" & linefeed & ""
  end if

  set messagesText to my _collectTexts(targetPopover)
  if my _hasSuccessText(messagesText) then
    my _closeFriendAddPopover()
    return "SUCCESS_MESSAGE" & linefeed & messagesText
  end if
  if my _hasErrorText(messagesText) then
    my _closeFriendAddPopover()
    return "ERROR" & linefeed & messagesText
  end if
end repeat

set targetPopover to my _findFriendAddPopover()
if targetPopover is missing value then
  return "SUCCESS_CLOSED" & linefeed & ""
end if
set messagesText to my _collectTexts(targetPopover)
if my _hasSuccessText(messagesText) then
  my _closeFriendAddPopover()
  return "SUCCESS_MESSAGE" & linefeed & messagesText
end if
my _closeFriendAddPopover()
return "STILL_OPEN" & linefeed & messagesText
"""

    result = _run_osascript(script)
    status, _, messages = result.partition("\n")
    if status == FRIEND_ADD_RESULT_SUCCESS:
        print("[Step 5] 친구 추가 완료: 팝오버가 닫혔습니다.")
        return True
    if status == FRIEND_ADD_RESULT_SUCCESS_MESSAGE:
        readable_messages = messages.strip() or "(성공 문구 없음)"
        print(f"[Step 5] 친구 추가 완료: {readable_messages} (팝오버 닫음)")
        return True

    readable_messages = messages.strip() or "(오류 문구 없음)"
    if status == FRIEND_ADD_RESULT_ERROR:
        print(
            f"[Step 5] 친구 추가 실패: {readable_messages} (팝오버 닫음)",
            file=sys.stderr,
        )
        return False

    raise KakaoMacError(
        "친구 추가 확정에 실패했습니다. "
        f"상태={status!r}, 화면 문구={readable_messages!r}"
    )


def prepare_friend_add() -> None:
    """친구추가 자동화를 시작할 수 있도록 친구추가 팝오버까지 연다."""
    step1_activate_kakao()
    step2_focus_friends_tab()
    step3_open_friend_add_popover()
    print("[친구추가] 친구추가 팝오버 진입 준비를 완료했습니다.")


def add_friend_by_contact(name: str, phone: str) -> bool:
    prepare_friend_add()
    step4_fill_contact_fields(name, phone)
    return step5_confirm_friend_add()


def _prompt_name_and_phone() -> tuple[str, str]:
    name = input("추가할 친구 이름: ").rstrip("\n")
    phone = input("전화번호: ").rstrip("\n")
    return name, phone


def _print_usage() -> None:
    print(
        f'사용법: python3 {sys.argv[0]} [이름] [전화번호]\n'
        f'  예) python3 {sys.argv[0]} "테스트1" "010-1111-1111"',
        file=sys.stderr,
    )


def main() -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)

        _ensure_macos()

        args = sys.argv[1:]
        if args and len(args) != 2:
            _print_usage()
            return 2

        ensure_accessibility_or_exit()

        if args:
            name, phone = args
        else:
            name, phone = _prompt_name_and_phone()

        if not add_friend_by_contact(name, phone):
            return 1
    except KakaoMacError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
