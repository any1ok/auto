#!/usr/bin/env python3
import argparse
import ctypes
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Union

K_CF_STRING_ENCODING_UTF8 = 0x08000100
K_AX_VALUE_CGPOINT_TYPE = 1
K_AX_VALUE_CGSIZE_TYPE = 2
AX_SUCCESS = 0
K_CG_HID_EVENT_TAP = 0
K_CG_EVENT_FLAG_MASK_COMMAND = 1 << 20


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


MAC_KEYCODES = {
    "a": 0,
    "f": 3,
    "v": 9,
    "2": 19,
    "return": 36,
    "tab": 48,
    "escape": 53,
    "command": 55,
    "enter": 76,
    "down": 125,
}


class DesktopTools(Protocol):
    def key_down(self, key: str) -> None:
        ...

    def key_up(self, key: str) -> None:
        ...

    def hotkey(self, *keys: str) -> None:
        ...

    def press(self, key: str) -> None:
        ...

    def paste_text(self, text: str) -> None:
        ...

    def click(self, x: int, y: int) -> None:
        ...

    def sleep(self, seconds: float) -> None:
        ...


class RealDesktopTools:
    def __init__(self) -> None:
        import pyautogui
        import pyperclip

        pyautogui.PAUSE = 0.08
        self.pyautogui = pyautogui
        self.pyperclip = pyperclip

    def key_down(self, key: str) -> None:
        self.pyautogui.keyDown(key)

    def key_up(self, key: str) -> None:
        self.pyautogui.keyUp(key)

    def hotkey(self, *keys: str) -> None:
        self.pyautogui.hotkey(*keys)

    def press(self, key: str) -> None:
        self.pyautogui.press(key)

    def paste_text(self, text: str) -> None:
        self.pyperclip.copy(text)
        if platform.system() == "Darwin":
            self.pyautogui.keyDown("command")
            time.sleep(0.08)
            self.pyautogui.press("v")
            time.sleep(0.08)
            self.pyautogui.keyUp("command")
        else:
            self.pyautogui.hotkey("ctrl", "v")

    def click(self, x: int, y: int) -> None:
        self.pyautogui.click(x=x, y=y)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def set_clipboard_text(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)


def macos_post_key(key: str, command: bool = False) -> bool:
    if platform.system() != "Darwin":
        return False

    try:
        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        core_foundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        app_services.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        app_services.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        app_services.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        app_services.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

        def post_key_event(keycode: int, down: bool, flags: int) -> bool:
            event = app_services.CGEventCreateKeyboardEvent(None, keycode, down)
            if not event:
                return False
            app_services.CGEventSetFlags(event, flags)
            app_services.CGEventPost(K_CG_HID_EVENT_TAP, event)
            core_foundation.CFRelease(event)
            return True

        keycode = MAC_KEYCODES[key]
        flags = K_CG_EVENT_FLAG_MASK_COMMAND if command else 0

        if command:
            if not post_key_event(MAC_KEYCODES["command"], True, flags):
                return False
            time.sleep(0.05)

        if not post_key_event(keycode, True, flags):
            return False
        time.sleep(0.04)

        if not post_key_event(keycode, False, flags):
            return False
        time.sleep(0.04)

        if command:
            if not post_key_event(MAC_KEYCODES["command"], False, 0):
                return False
            time.sleep(0.05)

        return True
    except Exception:
        return False


def macos_paste_text(text: str, tools: DesktopTools, steps: List[str]) -> None:
    set_clipboard_text(text)
    tools.sleep(0.1)
    if macos_post_key("v", command=True):
        steps.append("cg_event_command_v")
        return

    tools.paste_text(text)
    steps.append("pyautogui_command_v")


def macos_press_command_key(tools: DesktopTools, key: str) -> None:
    if macos_post_key(key, command=True):
        return

    tools.key_down("command")
    tools.sleep(0.08)
    tools.press(key)
    tools.sleep(0.08)
    tools.key_up("command")


def macos_press_send(
    tools: DesktopTools,
    steps: List[str],
    text_target: Optional[dict[str, object]] = None,
) -> None:
    if macos_click_send_button(tools, steps, text_target):
        return

    for key in ("return", "enter"):
        if not macos_post_key(key):
            tools.press(key)
        tools.sleep(0.15)
        steps.append(f"pressed_send_key:{key}")


@dataclass
class AutomationResult:
    ok: bool
    dryRun: bool
    sent: bool
    room: str
    message: str = ""
    error: str = ""
    steps: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "dryRun": self.dryRun,
                "sent": self.sent,
                "room": self.room,
                "message": self.message,
                "error": self.error,
                "steps": self.steps,
            },
            ensure_ascii=False,
        )


def macos_accessibility_trusted() -> bool:
    if platform.system() != "Darwin":
        return True

    try:
        application_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        application_services.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(application_services.AXIsProcessTrusted())
    except Exception:
        return False


def macos_request_accessibility() -> bool:
    if platform.system() != "Darwin":
        return True

    try:
        application_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        core_foundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )

        core_foundation.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        core_foundation.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        core_foundation.CFDictionaryCreate.restype = ctypes.c_void_p
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        application_services.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        application_services.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool

        key = core_foundation.CFStringCreateWithCString(
            None,
            b"AXTrustedCheckOptionPrompt",
            0x08000100,
        )
        value = ctypes.c_void_p.in_dll(core_foundation, "kCFBooleanTrue")
        keys = (ctypes.c_void_p * 1)(key)
        values = (ctypes.c_void_p * 1)(value.value)
        options = core_foundation.CFDictionaryCreate(None, keys, values, 1, None, None)
        trusted = bool(application_services.AXIsProcessTrustedWithOptions(options))
        core_foundation.CFRelease(options)
        core_foundation.CFRelease(key)
        return trusted
    except Exception:
        return macos_accessibility_trusted()


def macos_screen_recording_allowed() -> Optional[bool]:
    if platform.system() != "Darwin":
        return True

    try:
        import Quartz

        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return None


def macos_request_screen_recording() -> Optional[bool]:
    if platform.system() != "Darwin":
        return True

    try:
        import Quartz

        return bool(Quartz.CGRequestScreenCaptureAccess())
    except Exception:
        return macos_screen_recording_allowed()


def request_macos_automation_prompt() -> bool:
    if platform.system() != "Darwin":
        return True

    result = subprocess.run(
        ["osascript", "-e", 'tell application "KakaoTalk" to activate'],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.returncode == 0


def permission_status_json() -> str:
    system = platform.system()
    accessibility = macos_accessibility_trusted() if system == "Darwin" else True
    screen_recording = macos_screen_recording_allowed() if system == "Darwin" else True
    required = []
    optional = []

    if system == "Darwin" and not accessibility:
        required.append("손쉬운 사용")
    if system == "Darwin" and screen_recording is False:
        optional.append("화면 기록")

    return json.dumps(
        {
            "ok": len(required) == 0,
            "platform": system,
            "accessibility": accessibility,
            "screenRecording": screen_recording,
            "automation": None,
            "required": required,
            "optional": optional,
            "requested": [],
            "message": "손쉬운 사용 권한이 필요합니다." if required else "필수 권한이 준비되었습니다.",
        },
        ensure_ascii=False,
    )


def request_permissions_json(include_screen_recording: bool) -> str:
    requested = []
    if platform.system() == "Darwin":
        macos_request_accessibility()
        requested.append("손쉬운 사용")
        request_macos_automation_prompt()
        requested.append("자동화")
        if include_screen_recording:
            macos_request_screen_recording()
            requested.append("화면 기록")

    status = json.loads(permission_status_json())
    status["requested"] = requested
    if not status["ok"]:
        status["message"] = "권한 요청을 보냈습니다. 허용 후 AutoSend를 완전히 재시작하세요."
    return json.dumps(status, ensure_ascii=False)


def activate_kakaotalk(steps: List[str]) -> None:
    system = platform.system()
    if system == "Darwin":
        # `open -a` brings the app forward without requiring osascript to have
        # Accessibility permission. Keyboard/click automation is still guarded by
        # AXIsProcessTrusted before sending.
        result = subprocess.run(
            ["open", "-a", "KakaoTalk"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                "카카오톡 창을 활성화하지 못했습니다. macOS 자동화 권한에서 AutoSend/Electron/터미널이 KakaoTalk을 제어하도록 허용하세요."
                + (f" ({detail})" if detail else "")
            )
        steps.append("activated_kakaotalk_macos")
        return

    if system == "Windows":
        try:
            import pygetwindow

            windows = pygetwindow.getWindowsWithTitle("KakaoTalk") or pygetwindow.getWindowsWithTitle("카카오톡")
            if windows:
                windows[0].activate()
                steps.append("activated_kakaotalk_windows")
                return
        except Exception as exc:
            steps.append(f"windows_activation_skipped:{exc}")

    steps.append("activation_not_supported_or_not_found")


class MacAccessibility:
    def __init__(self) -> None:
        self.app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        self.core_foundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self._strings: dict[str, ctypes.c_void_p] = {}

        self.core_foundation.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self.core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.core_foundation.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        self.core_foundation.CFArrayGetCount.restype = ctypes.c_long
        self.core_foundation.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        self.core_foundation.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        self.core_foundation.CFStringGetCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        self.core_foundation.CFStringGetCString.restype = ctypes.c_bool
        self.core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

        self.app_services.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
        self.app_services.AXUIElementCreateApplication.restype = ctypes.c_void_p
        self.app_services.AXUIElementCopyAttributeValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.app_services.AXUIElementCopyAttributeValue.restype = ctypes.c_int
        self.app_services.AXUIElementSetAttributeValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.app_services.AXUIElementSetAttributeValue.restype = ctypes.c_int
        self.app_services.AXUIElementPerformAction.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.app_services.AXUIElementPerformAction.restype = ctypes.c_int
        self.app_services.AXValueGetValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self.app_services.AXValueGetValue.restype = ctypes.c_bool

    def cfstr(self, value: str) -> ctypes.c_void_p:
        if value not in self._strings:
            self._strings[value] = ctypes.c_void_p(
                self.core_foundation.CFStringCreateWithCString(
                    None,
                    value.encode("utf-8"),
                    K_CF_STRING_ENCODING_UTF8,
                )
            )
        return self._strings[value]

    def copy_attr(self, element: Union[int, ctypes.c_void_p], attr: str) -> Optional[ctypes.c_void_p]:
        output = ctypes.c_void_p()
        err = self.app_services.AXUIElementCopyAttributeValue(
            ctypes.c_void_p(element) if isinstance(element, int) else element,
            self.cfstr(attr),
            ctypes.byref(output),
        )
        if err != AX_SUCCESS or not output.value:
            return None
        return output

    def set_attr(self, element: Union[int, ctypes.c_void_p], attr: str, value: ctypes.c_void_p) -> bool:
        err = self.app_services.AXUIElementSetAttributeValue(
            ctypes.c_void_p(element) if isinstance(element, int) else element,
            self.cfstr(attr),
            value,
        )
        return err == AX_SUCCESS

    def perform_action(self, element: Union[int, ctypes.c_void_p], action: str) -> bool:
        err = self.app_services.AXUIElementPerformAction(
            ctypes.c_void_p(element) if isinstance(element, int) else element,
            self.cfstr(action),
        )
        return err == AX_SUCCESS

    def string_value(self, value: ctypes.c_void_p) -> str:
        buffer = ctypes.create_string_buffer(1024)
        if self.core_foundation.CFStringGetCString(value, buffer, len(buffer), K_CF_STRING_ENCODING_UTF8):
            return buffer.value.decode("utf-8", errors="ignore")
        return ""

    def array_values(self, value: ctypes.c_void_p) -> List[int]:
        count = self.core_foundation.CFArrayGetCount(value)
        return [int(self.core_foundation.CFArrayGetValueAtIndex(value, index)) for index in range(count)]

    def point_value(self, value: ctypes.c_void_p) -> Optional[tuple[int, int]]:
        point = CGPoint()
        if self.app_services.AXValueGetValue(value, K_AX_VALUE_CGPOINT_TYPE, ctypes.byref(point)):
            return int(point.x), int(point.y)
        return None

    def size_value(self, value: ctypes.c_void_p) -> Optional[tuple[int, int]]:
        size = CGSize()
        if self.app_services.AXValueGetValue(value, K_AX_VALUE_CGSIZE_TYPE, ctypes.byref(size)):
            return int(size.width), int(size.height)
        return None


def kakao_pid() -> Optional[int]:
    for command in (["pgrep", "-x", "KakaoTalk"], ["pgrep", "-if", "KakaoTalk"]):
        result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in result.stdout.splitlines():
            try:
                return int(line.strip())
            except ValueError:
                continue
    return None


def find_macos_kakao_text_input(steps: List[str]) -> Optional[dict[str, object]]:
    if platform.system() != "Darwin":
        return None

    pid = kakao_pid()
    if not pid:
        steps.append("ax_kakaotalk_pid_not_found")
        return None

    try:
        ax = MacAccessibility()
        app_element = ax.app_services.AXUIElementCreateApplication(pid)
        windows_ref = ax.copy_attr(app_element, "AXWindows")
        if not windows_ref:
            steps.append("ax_windows_not_found")
            return None

        window_elements = ax.array_values(windows_ref)
        queue = list(window_elements)
        best: Optional[dict[str, object]] = None
        visited = 0
        window_bounds: Optional[tuple[int, int, int, int]] = None

        if window_elements:
            window_position_ref = ax.copy_attr(window_elements[0], "AXPosition")
            window_size_ref = ax.copy_attr(window_elements[0], "AXSize")
            window_position = ax.point_value(window_position_ref) if window_position_ref else None
            window_size = ax.size_value(window_size_ref) if window_size_ref else None
            if window_position and window_size:
                window_bounds = (window_position[0], window_position[1], window_size[0], window_size[1])
                steps.append(f"ax_window_bounds:{window_bounds}")

        while queue and visited < 2500:
            visited += 1
            element = queue.pop(0)
            role_ref = ax.copy_attr(element, "AXRole")
            role = ax.string_value(role_ref) if role_ref else ""

            if role in {"AXTextArea", "AXTextField"}:
                position_ref = ax.copy_attr(element, "AXPosition")
                size_ref = ax.copy_attr(element, "AXSize")
                position = ax.point_value(position_ref) if position_ref else None
                size = ax.size_value(size_ref) if size_ref else None
                if position and size and size[0] >= 40 and size[1] >= 18:
                    score = position[1] * 2 + size[1] + min(size[0], 700)
                    if window_bounds:
                        _, win_y, win_width, win_height = window_bounds
                        lower_half = position[1] >= win_y + int(win_height * 0.45)
                        wide_enough = size[0] >= min(260, max(180, int(win_width * 0.25)))
                        if not lower_half:
                            steps.append(f"ax_text_input_rejected:{role}:{position}:{size}")
                            continue
                        if not wide_enough:
                            steps.append(f"ax_text_input_narrow_candidate:{role}:{position}:{size}")
                            score -= 350
                    if best is None or score > int(best["score"]):
                        best = {
                            "element": element,
                            "position": position,
                            "size": size,
                            "score": score,
                            "role": role,
                        }

            children_ref = ax.copy_attr(element, "AXChildren")
            if children_ref:
                queue.extend(ax.array_values(children_ref))

        steps.append(f"ax_visited:{visited}")
        if best:
            position = best["position"]
            size = best["size"]
            steps.append(f"ax_text_input:{best['role']}:{position}:{size}")
            best["ax"] = ax
            return best
        steps.append("ax_text_input_not_found")
        return None
    except Exception as exc:
        steps.append(f"ax_error:{exc}")
        return None


def macos_ax_string_attribute(ax: MacAccessibility, element: int, attr: str) -> Optional[str]:
    value_ref = ax.copy_attr(element, attr)
    if not value_ref:
        return None
    value = ax.string_value(value_ref)
    return value if value else ""


def macos_ax_text_contains(ax: MacAccessibility, element: int, message: str) -> Optional[bool]:
    readable = False
    for attr in ("AXValue", "AXSelectedText"):
        value = macos_ax_string_attribute(ax, element, attr)
        if value is None:
            continue
        readable = True
        if message in value:
            return True
    return False if readable else None


def macos_set_text_input_value(target: dict[str, object], message: str, tools: DesktopTools, steps: List[str]) -> bool:
    ax = target["ax"]
    element = int(target["element"])
    assert isinstance(ax, MacAccessibility)

    if not ax.set_attr(element, "AXValue", ax.cfstr(message)):
        steps.append("ax_set_message_value_failed")
        return False

    tools.sleep(0.15)
    verified = macos_ax_text_contains(ax, element, message)
    if verified is True:
        steps.append("ax_set_message_value_verified")
        return True
    if verified is False:
        steps.append("ax_set_message_value_not_visible")
        return False

    steps.append("ax_set_message_value_unverified")
    return True


def find_macos_send_button(
    steps: List[str],
    text_target: Optional[dict[str, object]],
) -> Optional[dict[str, object]]:
    if platform.system() != "Darwin":
        return None

    pid = kakao_pid()
    if not pid:
        steps.append("ax_send_button_pid_not_found")
        return None

    input_position: Optional[tuple[int, int]] = None
    input_size: Optional[tuple[int, int]] = None
    if text_target:
        maybe_position = text_target.get("position")
        maybe_size = text_target.get("size")
        if isinstance(maybe_position, tuple) and isinstance(maybe_size, tuple):
            input_position = maybe_position
            input_size = maybe_size

    try:
        ax = MacAccessibility()
        app_element = ax.app_services.AXUIElementCreateApplication(pid)
        windows_ref = ax.copy_attr(app_element, "AXWindows")
        if not windows_ref:
            steps.append("ax_send_button_windows_not_found")
            return None

        queue = ax.array_values(windows_ref)
        best: Optional[dict[str, object]] = None
        visited = 0
        label_words = ("전송", "보내기", "send")

        while queue and visited < 2500:
            visited += 1
            element = queue.pop(0)
            role_ref = ax.copy_attr(element, "AXRole")
            role = ax.string_value(role_ref) if role_ref else ""

            if role == "AXButton":
                title = macos_ax_string_attribute(ax, element, "AXTitle") or ""
                description = macos_ax_string_attribute(ax, element, "AXDescription") or ""
                help_text = macos_ax_string_attribute(ax, element, "AXHelp") or ""
                label = " ".join(part for part in (title, description, help_text) if part).strip()
                normalized_label = label.casefold()
                position_ref = ax.copy_attr(element, "AXPosition")
                size_ref = ax.copy_attr(element, "AXSize")
                position = ax.point_value(position_ref) if position_ref else None
                size = ax.size_value(size_ref) if size_ref else None
                score = 0

                if any(word in normalized_label for word in label_words):
                    score += 10000

                if input_position and input_size and position and size:
                    input_x, input_y = input_position
                    input_width, input_height = input_size
                    button_x, button_y = position
                    button_width, button_height = size
                    horizontally_near_input = button_x >= input_x + input_width - 12
                    vertically_near_input = input_y - 32 <= button_y <= input_y + input_height + 48
                    visible_button_size = 10 <= button_width <= 140 and 10 <= button_height <= 80
                    if horizontally_near_input and vertically_near_input and visible_button_size:
                        score += 1000
                        score -= abs(button_y + button_height // 2 - (input_y + input_height // 2))
                        score -= abs(button_x - (input_x + input_width))

                if score > 0 and position and size and (best is None or score > int(best["score"])):
                    best = {
                        "ax": ax,
                        "element": element,
                        "position": position,
                        "size": size,
                        "score": score,
                        "label": label,
                    }

            children_ref = ax.copy_attr(element, "AXChildren")
            if children_ref:
                queue.extend(ax.array_values(children_ref))

        steps.append(f"ax_send_button_visited:{visited}")
        if best:
            steps.append(f"ax_send_button:{best['label'] or 'unlabeled'}:{best['position']}:{best['size']}")
            return best
        steps.append("ax_send_button_not_found")
        return None
    except Exception as exc:
        steps.append(f"ax_send_button_error:{exc}")
        return None


def macos_click_send_button(
    tools: DesktopTools,
    steps: List[str],
    text_target: Optional[dict[str, object]],
) -> bool:
    button = find_macos_send_button(steps, text_target)
    if not button:
        return False

    ax = button["ax"]
    element = int(button["element"])
    position = button["position"]
    size = button["size"]
    assert isinstance(ax, MacAccessibility)
    assert isinstance(position, tuple)
    assert isinstance(size, tuple)

    if ax.perform_action(element, "AXPress"):
        steps.append("pressed_send_button_ax")
        return True

    tools.click(position[0] + size[0] // 2, position[1] + size[1] // 2)
    steps.append("clicked_send_button")
    return True


def run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-e", script],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_osascript_stdin(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript"],
        input=script,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def macos_front_window_title() -> str:
    if platform.system() != "Darwin":
        return ""

    script = '''
tell application "System Events"
  tell process "KakaoTalk"
    if (count of windows) is 0 then return ""
    return name of front window
  end tell
end tell
'''
    result = run_osascript(script)
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def macos_front_window_bounds() -> Optional[tuple[int, int, int, int]]:
    if platform.system() != "Darwin":
        return None

    script = '''
tell application "System Events"
  tell process "KakaoTalk"
    if (count of windows) is 0 then return ""
    set windowPosition to position of front window
    set windowSize to size of front window
    return (item 1 of windowPosition as text) & "," & (item 2 of windowPosition as text) & "," & (item 1 of windowSize as text) & "," & (item 2 of windowSize as text)
  end tell
end tell
'''
    result = run_osascript(script)
    if result.returncode != 0:
        return None

    try:
        x, y, width, height = [int(float(part)) for part in result.stdout.strip().split(",")]
        return x, y, width, height
    except ValueError:
        return None


def room_title_matches(room: str, title: str) -> bool:
    normalized_room = " ".join(room.strip().split()).casefold()
    normalized_title = " ".join(title.strip().split()).casefold()
    return bool(normalized_room and normalized_room in normalized_title)


def focus_macos_message_input(tools: DesktopTools, steps: List[str]) -> bool:
    bounds = macos_front_window_bounds()
    if not bounds:
        tools.press("tab")
        steps.append("focused_message_input_with_tab_fallback")
        return False

    x, y, width, height = bounds
    input_x = x + width // 2
    input_y = y + max(80, height - 44)
    tools.click(input_x, input_y)
    tools.sleep(0.15)
    steps.append(f"clicked_message_input_area:{input_x},{input_y}")
    return True


def macos_paste_message_and_maybe_send(message: str, dry_run: bool, tools: DesktopTools, steps: List[str]) -> None:
    focus_macos_message_input(tools, steps)
    macos_press_command_key(tools, "a")
    steps.append("selected_existing_message_text")
    macos_paste_text(message, tools, steps)
    tools.sleep(0.2)
    steps.append("paste_message_unverified")
    steps.append("message_ready")
    if dry_run:
        steps.append("dry_run_requested_but_send_forced")
    macos_press_send(tools, steps)
    steps.append("pressed_send")


def open_kakao_room(room: str, tools: DesktopTools, steps: List[str], search_delay: float) -> None:
    system = platform.system()
    activate_kakaotalk(steps)
    tools.sleep(0.5)

    if system == "Darwin" and room_title_matches(room, macos_front_window_title()):
        steps.append("room_already_open")
        return

    modifier = "command" if system == "Darwin" else "ctrl"

    if system == "Darwin":
        tools.press("escape")
        tools.sleep(0.1)
        macos_press_command_key(tools, "2")
        steps.append("selected_chat_tab_macos")
        tools.sleep(0.3)

    if system == "Darwin":
        macos_press_command_key(tools, "f")
    else:
        tools.hotkey(modifier, "f")
    steps.append("opened_search")
    tools.sleep(0.2)
    if system == "Darwin":
        macos_press_command_key(tools, "a")
    else:
        tools.hotkey(modifier, "a")
    tools.sleep(0.1)
    tools.paste_text(room)
    steps.append("pasted_room")
    tools.sleep(search_delay)

    attempts = [
        ("enter", ["enter"]),
        ("down_enter", ["down", "enter"]),
        ("tab_enter", ["tab", "enter"]),
    ]

    for label, keys in attempts:
        for key in keys:
            tools.press(key)
            tools.sleep(0.15)
        tools.sleep(0.8)
        steps.append(f"open_room_attempt:{label}")
        if system != "Darwin":
            return

        title = macos_front_window_title()
        steps.append(f"front_window_title:{title}")
        if not title:
            steps.append("front_window_title_unavailable_proceeding_unverified")
            return
        if room_title_matches(room, title):
            steps.append("opened_room_verified")
            return

    raise RuntimeError(
        f"카카오톡 채팅방을 열지 못했습니다. 검색 결과에서 '{room}' 방이 선택되지 않았습니다. "
        "방 이름이 정확한지, 카카오톡이 채팅 목록 화면에서 검색 가능한 상태인지 확인하세요."
    )


def run_kakao_send(room: str, message: str, dry_run: bool, tools: DesktopTools, search_delay: float = 0.7) -> AutomationResult:
    steps: List[str] = []
    if not room.strip():
        return AutomationResult(False, dry_run, False, room, message, "카카오톡 방 이름이 비어 있습니다.", steps)
    if not message.strip():
        return AutomationResult(False, dry_run, False, room, message, "메시지가 비어 있습니다.", steps)
    if platform.system() == "Darwin" and not macos_accessibility_trusted():
        return AutomationResult(
            False,
            dry_run,
            False,
            room,
            message,
            "macOS 손쉬운 사용 권한이 없습니다. AutoSend/Electron/터미널/Python 중 권한 목록에 표시되는 항목을 허용한 뒤 앱을 재시작하세요.",
            steps,
        )

    try:
        open_kakao_room(room, tools, steps, search_delay)
        tools.sleep(0.4)
        if platform.system() == "Darwin":
            macos_paste_message_and_maybe_send(message, dry_run, tools, steps)
            return AutomationResult(True, dry_run, True, room, message, "", steps)

        tools.paste_text(message)
        steps.append("pasted_message")

        if dry_run:
            steps.append("dry_run_requested_but_send_forced")
        tools.press("enter")
        steps.append("pressed_send")
        return AutomationResult(True, dry_run, True, room, message, "", steps)
    except Exception as exc:
        return AutomationResult(False, dry_run, False, room, message, str(exc), steps)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AutoSend KakaoTalk UI automation")
    parser.add_argument("--room", help="KakaoTalk room name")
    parser.add_argument("--message", help="Message text")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compatibility flag only. Current behavior still sends after opening the room and entering text.",
    )
    parser.add_argument("--check-permissions", action="store_true", help="Print permission status and exit")
    parser.add_argument("--request-permissions", action="store_true", help="Request required macOS permissions and exit")
    parser.add_argument(
        "--request-screen-recording",
        action="store_true",
        help="Also request optional macOS screen recording permission",
    )
    parser.add_argument("--search-delay", type=float, default=0.7, help="Seconds to wait after room search")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if args.check_permissions:
        print(permission_status_json())
        return 0
    if args.request_permissions:
        print(request_permissions_json(args.request_screen_recording))
        return 0

    if not args.room or not args.message:
        print(AutomationResult(False, args.dry_run, False, args.room or "", args.message or "", "room and message are required").to_json())
        return 1

    try:
        tools = RealDesktopTools()
    except ModuleNotFoundError as exc:
        missing = exc.name or "required package"
        result = AutomationResult(
            False,
            args.dry_run,
            False,
            args.room or "",
            args.message or "",
            f"Python package is missing: {missing}. Run `npm run setup:automation`.",
            [],
        )
        print(result.to_json())
        return 1

    result = run_kakao_send(
        room=args.room,
        message=args.message,
        dry_run=args.dry_run,
        tools=tools,
        search_delay=args.search_delay,
    )
    print(result.to_json())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
