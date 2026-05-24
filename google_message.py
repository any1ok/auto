"""Google Messages Web automation without third-party packages.

Step 1: Open https://messages.google.com/web/conversations in real Chrome.
Step 2: Click Start chat, enter a phone number, and verify the contact name.
Step 3: Click the "Send to {phone}" / "{phone} 번으로 보내기" button.
Step 4: Type a message and click Send.

This script intentionally does not use Selenium, ChromeDriver, or Playwright.
It launches or attaches to a visible, installed Chrome instance through the
Chrome DevTools Protocol (CDP), then speaks CDP over a localhost WebSocket using
only Python's standard library. That keeps the browser as real Chrome and avoids
the "browser or app may not be secure" WebDriver login path.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


MESSAGES_URL = "https://messages.google.com/web/conversations"
DEFAULT_DEBUG_PORT = 9222
DEFAULT_PROFILE_DIR = Path(__file__).resolve().parent / ".google_messages_chrome_profile"
DEFAULT_LOGIN_TIMEOUT_S = 180
DEFAULT_ACTION_TIMEOUT_MS = 15_000
CONTACT_VERIFY_TIMEOUT_S = 1.5

START_CHAT_PATTERN = (
    r"(Start\s*chat|New\s*(chat|conversation)|채팅\s*시작|새\s*(채팅|대화)|대화\s*시작)"
)
RECIPIENT_PATTERN = (
    r"(To|Recipient|Name|phone|email|받는\s*사람|수신자|이름|전화|이메일)"
)
COMPOSER_PATTERN = (
    r"(Text\s*message|RCS\s*message|Type\s*a\s*message|Message|문자\s*메시지|메시지\s*입력)"
)
SEND_TO_PATTERN = r"(번으로\s*보내기|Send\s+to|Text\s+)"
UNSAFE_BROWSER_RE = re.compile(
    r"(browser or app may not be secure|브라우저 또는 앱이 안전하지 않을 수|"
    r"앱이 안전하지 않을 수|couldn'?t sign you in|로그인할 수 없음)",
    re.IGNORECASE,
)


class GoogleMessageError(Exception):
    """Google Messages automation failure."""


class CDPError(GoogleMessageError):
    """Chrome DevTools Protocol failure."""


def _normalize_digits(value: str) -> str:
    return re.sub(r"\D+", "", value)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_phone(value: str) -> bool:
    digits = _normalize_digits(value)
    return len(digits) >= 7 and bool(re.search(r"\d", value))


def _chrome_candidates() -> list[Path]:
    system = platform.system()
    candidates: list[Path] = []

    if system == "Darwin":
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path.home()
                / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ]
        )
    elif system == "Windows":
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    path_chrome = shutil.which("chrome") or shutil.which("chrome.exe")
    if path_chrome:
        candidates.append(Path(path_chrome))

    return candidates


def _find_chrome_executable(explicit: Optional[str]) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path
        raise GoogleMessageError(f"Chrome 실행 파일을 찾을 수 없습니다: {path}")

    for candidate in _chrome_candidates():
        if candidate.exists():
            return candidate

    raise GoogleMessageError(
        "Google Chrome 실행 파일을 찾을 수 없습니다. --chrome-executable 로 경로를 지정하세요."
    )


def _http_json(
    port: int,
    path: str,
    *,
    method: str = "GET",
    timeout_s: float = 1.0,
) -> Any:
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else None


def _http_text(
    port: int,
    path: str,
    *,
    method: str = "GET",
    timeout_s: float = 1.0,
) -> str:
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return response.read().decode("utf-8", errors="replace")


def _is_cdp_ready(port: int) -> bool:
    try:
        data = _http_json(port, "/json/version", timeout_s=0.7)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and ("webSocketDebuggerUrl" in data or "Browser" in data)


def _wait_for_cdp(port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _is_cdp_ready(port):
            return True
        time.sleep(0.2)
    return False


def _launch_chrome_for_cdp(args: argparse.Namespace) -> subprocess.Popen:
    chrome = _find_chrome_executable(args.chrome_executable)
    profile_dir = Path(args.user_data_dir).expanduser() if args.user_data_dir else DEFAULT_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    chrome_args = [
        str(chrome),
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "about:blank",
    ]
    if args.profile_directory:
        chrome_args.insert(-1, f"--profile-directory={args.profile_directory}")

    print(f"[Chrome] 실제 Chrome을 디버그 포트로 실행합니다: {chrome}")
    print(f"[Chrome] 전용 프로필: {profile_dir}")

    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(chrome_args, **popen_kwargs)


def ensure_chrome_cdp(args: argparse.Namespace) -> str:
    if _is_cdp_ready(args.port):
        print(f"[Chrome] 실행 중인 Chrome CDP 세션에 연결합니다: 127.0.0.1:{args.port}")
        return f"http://127.0.0.1:{args.port}"

    if args.attach_only:
        raise GoogleMessageError(
            f"127.0.0.1:{args.port} 에 연결 가능한 Chrome CDP 세션이 없습니다. "
            "Chrome을 --remote-debugging-port 옵션으로 먼저 실행하세요."
        )

    _launch_chrome_for_cdp(args)
    if not _wait_for_cdp(args.port, timeout_s=10):
        raise GoogleMessageError(
            "Chrome은 실행했지만 CDP 포트가 열리지 않았습니다. "
            "이미 같은 user-data-dir 로 열린 Chrome이 있거나 Chrome 정책이 원격 디버깅을 막고 있을 수 있습니다."
        )
    return f"http://127.0.0.1:{args.port}"


class WebSocketConnection:
    """Small RFC 6455 client for ws://localhost CDP targets."""

    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, ws_url: str, timeout_s: float = 10.0) -> None:
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws":
            raise CDPError(f"지원하지 않는 WebSocket URL 입니다: {ws_url}")

        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        self.sock = socket.create_connection((host, port), timeout=timeout_s)
        self.sock.settimeout(timeout_s)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))

        response = self._read_http_response()
        if " 101 " not in response.split("\r\n", 1)[0]:
            raise CDPError(f"CDP WebSocket 연결 실패: {response.splitlines()[0]}")

        expected_accept = base64.b64encode(
            hashlib.sha1((key + self.GUID).encode("ascii")).digest()
        ).decode("ascii")
        if expected_accept.lower() not in response.lower():
            raise CDPError("CDP WebSocket handshake 검증에 실패했습니다.")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_http_response(self) -> str:
        chunks: list[bytes] = []
        while True:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in b"".join(chunks):
                break
        return b"".join(chunks).decode("iso-8859-1", errors="replace")

    def _recv_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise CDPError("CDP WebSocket 연결이 닫혔습니다.")
            data.extend(chunk)
        return bytes(data)

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _send_control(self, opcode: int, payload: bytes = b"") -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length >= 126:
            raise CDPError("WebSocket control frame payload is too large.")
        header.append(0x80 | length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_text(self, timeout_s: float = 10.0) -> str:
        self.sock.settimeout(timeout_s)
        fragments: list[bytes] = []

        while True:
            first, second = self._recv_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F

            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]

            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

            if opcode == 0x8:
                raise CDPError("CDP WebSocket close frame을 받았습니다.")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x0):
                fragments.append(payload)
                if fin:
                    return b"".join(fragments).decode("utf-8")
                continue

            raise CDPError(f"지원하지 않는 WebSocket opcode 입니다: {opcode}")


class CDPClient:
    def __init__(self, ws_url: str) -> None:
        self.ws = WebSocketConnection(ws_url)
        self.next_id = 0

    def close(self) -> None:
        self.ws.close()

    def call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        payload: dict[str, Any] = {"id": message_id, "method": method}
        if params is not None:
            payload["params"] = params

        self.ws.send_text(json.dumps(payload, separators=(",", ":")))
        deadline = time.monotonic() + timeout_s

        while True:
            remaining = max(0.1, deadline - time.monotonic())
            if time.monotonic() >= deadline:
                raise CDPError(f"CDP 응답 타임아웃: {method}")

            raw = self.ws.recv_text(timeout_s=remaining)
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if message.get("id") != message_id:
                continue

            if "error" in message:
                error = message["error"]
                raise CDPError(
                    f"CDP 호출 실패: {method}: {error.get('message') or error}"
                )
            return message.get("result", {})

    def evaluate(
        self,
        expression: str,
        *,
        timeout_s: float = 10.0,
        await_promise: bool = False,
    ) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": True,
            },
            timeout_s=timeout_s,
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("text") or details.get("exception", {}).get("description")
            raise CDPError(f"페이지 JS 실행 실패: {text}")
        remote_object = result.get("result", {})
        return remote_object.get("value")


def _get_or_create_target(port: int, wanted_url: str) -> dict[str, Any]:
    try:
        targets = _http_json(port, "/json/list", timeout_s=2.0)
    except Exception as exc:
        raise GoogleMessageError(f"Chrome target 목록을 읽지 못했습니다: {exc}") from exc

    if isinstance(targets, list):
        for target in targets:
            if (
                target.get("type") == "page"
                and "messages.google.com/web" in target.get("url", "")
                and target.get("webSocketDebuggerUrl")
            ):
                return target

        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return target

    encoded_url = urllib.parse.quote("about:blank", safe="")
    for method in ("PUT", "GET"):
        try:
            target = _http_json(port, f"/json/new?{encoded_url}", method=method, timeout_s=2.0)
            if isinstance(target, dict) and target.get("webSocketDebuggerUrl"):
                return target
        except Exception:
            continue

    raise GoogleMessageError("새 Chrome tab target을 만들지 못했습니다.")


def _is_messages_target(target: dict[str, Any]) -> bool:
    return target.get("type") == "page" and "messages.google.com/web" in target.get("url", "")


def _activate_target(port: int, target_id: str) -> None:
    if not target_id:
        return
    try:
        _http_text(port, f"/json/activate/{target_id}", timeout_s=1.0)
    except Exception:
        pass


def _js_regex(pattern: str) -> str:
    return json.dumps(pattern, ensure_ascii=False)


def _visible_helper_js() -> str:
    return """
      const visible = (el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' &&
               style.visibility !== 'hidden' &&
               rect.width > 0 &&
               rect.height > 0;
      };
      const center = (el) => {
        const rect = el.getBoundingClientRect();
        return {
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
          width: rect.width,
          height: rect.height
        };
      };
    """


def _body_text(cdp: CDPClient) -> str:
    value = cdp.evaluate("document.body ? document.body.innerText : ''", timeout_s=2.0)
    return value if isinstance(value, str) else ""


def _debug_paths(debug_dir: Path, step: str) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_step = re.sub(r"[^A-Za-z0-9_.-]+", "_", step).strip("_") or "debug"
    return (
        debug_dir / f"{stamp}_{safe_step}.png",
        debug_dir / f"{stamp}_{safe_step}.html",
    )


def save_debug_artifacts(cdp: CDPClient, debug_dir: Path, step: str) -> list[Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path, html_path = _debug_paths(debug_dir, step)
    saved: list[Path] = []

    try:
        result = cdp.call(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True},
            timeout_s=10.0,
        )
        data = result.get("data")
        if data:
            screenshot_path.write_bytes(base64.b64decode(data))
            saved.append(screenshot_path)
    except Exception:
        pass

    try:
        html = cdp.evaluate("document.documentElement.outerHTML", timeout_s=5.0)
        if isinstance(html, str):
            html_path.write_text(html, encoding="utf-8")
            saved.append(html_path)
    except Exception:
        pass

    return saved


def fail_with_debug(
    cdp: CDPClient,
    args: argparse.Namespace,
    step: str,
    message: str,
) -> None:
    paths = save_debug_artifacts(cdp, Path(args.debug_dir), step)
    suffix = ""
    if paths:
        suffix = "\n디버그 파일:\n" + "\n".join(f"  - {path}" for path in paths)
    raise GoogleMessageError(message + suffix)


def _click_point(cdp: CDPClient, x: float, y: float) -> None:
    cdp.call(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": x, "y": y, "button": "none", "pointerType": "mouse"},
        timeout_s=5.0,
    )
    cdp.call(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "buttons": 1,
            "clickCount": 1,
            "pointerType": "mouse",
        },
        timeout_s=5.0,
    )
    time.sleep(0.05)
    cdp.call(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "buttons": 0,
            "clickCount": 1,
            "pointerType": "mouse",
        },
        timeout_s=5.0,
    )


def _press_enter(cdp: CDPClient) -> None:
    cdp.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyDown",
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "text": "\r",
            "unmodifiedText": "\r",
        },
        timeout_s=5.0,
    )
    cdp.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
        },
        timeout_s=5.0,
    )


def _insert_text(cdp: CDPClient, text: str) -> None:
    cdp.call("Input.insertText", {"text": text}, timeout_s=5.0)


def _find_start_chat(cdp: CDPClient) -> dict[str, Any]:
    return cdp.evaluate(
        f"""
        (() => {{
          const re = new RegExp({_js_regex(START_CHAT_PATTERN)}, 'i');
          {_visible_helper_js()}
          const preferred = document.querySelector('[data-e2e-start-button], mw-fab-link.start-chat a, a[href*="/web/conversations/new"]');
          if (preferred && visible(preferred)) {{
            const label = [
              preferred.getAttribute('aria-label') || '',
              preferred.getAttribute('title') || '',
              preferred.innerText || '',
              preferred.textContent || ''
            ].join(' ').trim();
            return {{
              found: true,
              selector: 'data-e2e-start-button',
              label,
              href: preferred.href || preferred.getAttribute('href') || '',
              ...center(preferred)
            }};
          }}
          const selectors = [
            'button',
            'a',
            '[role="button"]',
            '[aria-label]'
          ].join(',');
          for (const el of document.querySelectorAll(selectors)) {{
            const label = [
              el.getAttribute('aria-label') || '',
              el.getAttribute('title') || '',
              el.innerText || '',
              el.textContent || ''
            ].join(' ').trim();
            if (visible(el) && re.test(label)) {{
              return {{
                found: true,
                selector: '',
                label,
                href: el.href || el.getAttribute('href') || '',
                ...center(el)
              }};
            }}
          }}
          return {{ found: false }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def _new_conversation_visible(cdp: CDPClient) -> bool:
    return bool(
        cdp.evaluate(
            f"""
            (() => {{
              const re = new RegExp({_js_regex(RECIPIENT_PATTERN)}, 'i');
              const composerRe = new RegExp({_js_regex(COMPOSER_PATTERN)}, 'i');
              {_visible_helper_js()}
              const sendTo = document.querySelector('[data-e2e-send-to-button]');
              if (sendTo && visible(sendTo)) return true;
              const isNewPath = /\\/web\\/conversations\\/new(?:$|[?#/])/.test(location.pathname + location.search + location.hash);
              const selectors = 'input, textarea, [contenteditable="true"], [role="textbox"]';
              for (const el of document.querySelectorAll(selectors)) {{
                if (!visible(el)) continue;
                const label = [
                  el.getAttribute('aria-label') || '',
                  el.getAttribute('placeholder') || '',
                  el.getAttribute('title') || '',
                  el.getAttribute('name') || '',
                  el.innerText || '',
                  el.textContent || ''
                ].join(' ');
                if (re.test(label)) return true;
                if (isNewPath && !composerRe.test(label)) return true;
              }}
              return false;
            }})()
            """,
            timeout_s=3.0,
        )
    )


def _route_to_new_conversation(cdp: CDPClient) -> str:
    current_origin = cdp.evaluate("location.origin", timeout_s=3.0) or "https://messages.google.com"
    target_url = urllib.parse.urljoin(str(current_origin), "/web/conversations/new")
    cdp.evaluate(
        """
        (() => {
          const anchor = document.querySelector('[data-e2e-start-button], mw-fab-link.start-chat a, a[href*="/web/conversations/new"]');
          if (anchor) {
            anchor.click();
          }
          return true;
        })()
        """,
        timeout_s=5.0,
    )
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if _new_conversation_visible(cdp):
            return "dom_click"
        time.sleep(0.2)

    if not _new_conversation_visible(cdp):
        cdp.call("Page.navigate", {"url": target_url}, timeout_s=10.0)
    return "navigate"


def wait_for_start_chat(cdp: CDPClient, args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.login_timeout
    reported_wait = False

    while time.monotonic() < deadline:
        try:
            body = _body_text(cdp)
        except CDPError:
            time.sleep(0.5)
            continue
        if UNSAFE_BROWSER_RE.search(body):
            fail_with_debug(
                cdp,
                args,
                "unsafe_browser",
                "Google 로그인 화면에서 '브라우저 또는 앱이 안전하지 않을 수 있습니다' 메시지가 감지됐습니다. "
                "Selenium/ChromeDriver가 아니라 실제 Chrome CDP 프로필을 사용해야 합니다. "
                "기본 실행값의 전용 Chrome 프로필에서 직접 로그인/페어링한 뒤 다시 실행하세요.",
            )

        try:
            info = _find_start_chat(cdp)
        except CDPError:
            time.sleep(0.5)
            continue
        if info.get("found"):
            return

        if not reported_wait:
            print(
                "[대기] Chrome 창에서 Google 로그인 또는 Messages 휴대전화 페어링을 완료하세요. "
                "완료되면 자동으로 Step 2 로 진행합니다."
            )
            reported_wait = True
        time.sleep(1)

    fail_with_debug(
        cdp,
        args,
        "start_chat_not_found",
        f"{args.login_timeout}s 안에 '채팅 시작/Start chat' 버튼을 찾지 못했습니다.",
    )


def step1_open_messages(cdp: CDPClient, args: argparse.Namespace) -> None:
    cdp.call("Page.enable", timeout_s=5.0)
    cdp.call("Runtime.enable", timeout_s=5.0)
    cdp.call("Page.bringToFront", timeout_s=5.0)
    cdp.call("Page.navigate", {"url": args.url}, timeout_s=10.0)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            state = cdp.evaluate("document.readyState", timeout_s=2.0)
        except CDPError:
            time.sleep(0.2)
            continue
        if state in ("interactive", "complete"):
            break
        time.sleep(0.2)

    cdp.call("Page.bringToFront", timeout_s=5.0)
    print(f"[Step 1] Google Messages 페이지를 Chrome에 열었습니다: {args.url}")
    wait_for_start_chat(cdp, args)
    print("[Step 1] '채팅 시작/Start chat' 버튼을 확인했습니다.")


def use_existing_messages_page(cdp: CDPClient, args: argparse.Namespace) -> None:
    cdp.call("Page.enable", timeout_s=5.0)
    cdp.call("Runtime.enable", timeout_s=5.0)
    cdp.call("Page.bringToFront", timeout_s=5.0)

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            state = cdp.evaluate("document.readyState", timeout_s=2.0)
        except CDPError:
            time.sleep(0.2)
            continue
        if state in ("interactive", "complete"):
            break
        time.sleep(0.2)

    current_url = cdp.evaluate("location.href", timeout_s=3.0)
    print(f"[Step 1] 이미 열린 Google Messages 탭을 감지했습니다: {current_url}")

    body = _body_text(cdp)
    if UNSAFE_BROWSER_RE.search(body):
        fail_with_debug(
            cdp,
            args,
            "unsafe_browser",
            "Google 로그인 화면에서 '브라우저 또는 앱이 안전하지 않을 수 있습니다' 메시지가 감지됐습니다. "
            "Selenium/ChromeDriver가 아니라 실제 Chrome CDP 프로필을 사용해야 합니다. "
            "기본 실행값의 전용 Chrome 프로필에서 직접 로그인/페어링한 뒤 다시 실행하세요.",
        )

    if _new_conversation_visible(cdp) or _find_start_chat(cdp).get("found"):
        print("[Step 1] 페이지 열기 단계는 생략하고 Step 2부터 시작합니다.")
        return

    wait_for_start_chat(cdp, args)
    print("[Step 1] 페이지 열기 단계는 생략하고 Step 2부터 시작합니다.")


def click_start_chat(cdp: CDPClient, args: argparse.Namespace) -> None:
    info = _find_start_chat(cdp)
    if not info.get("found"):
        fail_with_debug(
            cdp,
            args,
            "click_start_chat_failed",
            "채팅 시작 버튼을 찾았지만 클릭하지 못했습니다.",
        )

    _click_point(cdp, float(info["x"]), float(info["y"]))
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if _new_conversation_visible(cdp):
            print("[Step 2] 채팅 시작 버튼을 클릭했습니다.")
            return
        time.sleep(0.2)

    fallback = _route_to_new_conversation(cdp)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if _new_conversation_visible(cdp):
            if fallback == "dom_click":
                print("[Step 2] 채팅 시작 버튼을 클릭했습니다. (DOM click fallback)")
            else:
                print("[Step 2] 채팅 시작 화면으로 이동했습니다. (route fallback)")
            return
        time.sleep(0.2)

    fail_with_debug(
        cdp,
        args,
        "click_start_chat_no_route",
        "채팅 시작 버튼을 클릭/라우팅했지만 새 대화 화면으로 이동하지 못했습니다.",
    )


def _focus_and_clear_recipient_input(cdp: CDPClient) -> dict[str, Any]:
    return cdp.evaluate(
        f"""
        (() => {{
          const re = new RegExp({_js_regex(RECIPIENT_PATTERN)}, 'i');
          const composerRe = new RegExp({_js_regex(COMPOSER_PATTERN)}, 'i');
          {_visible_helper_js()}
          const selectors = [
            'input',
            'textarea',
            '[contenteditable="true"]',
            '[role="textbox"]'
          ].join(',');
          const nodes = Array.from(document.querySelectorAll(selectors)).filter(visible);
          const candidates = nodes.filter((el) => {{
            const label = [
              el.getAttribute('aria-label') || '',
              el.getAttribute('placeholder') || '',
              el.getAttribute('title') || '',
              el.getAttribute('name') || '',
              el.innerText || '',
              el.textContent || ''
            ].join(' ');
            return !composerRe.test(label);
          }});

          let picked = null;
          for (const el of candidates) {{
            const label = [
              el.getAttribute('aria-label') || '',
              el.getAttribute('placeholder') || '',
              el.getAttribute('title') || '',
              el.getAttribute('name') || '',
              el.innerText || '',
              el.textContent || ''
            ].join(' ');
            if (re.test(label)) {{
              picked = el;
              break;
            }}
          }}
          if (!picked && candidates.length) picked = candidates[0];
          if (!picked) return {{ found: false }};

          picked.focus();
          if (picked.tagName === 'INPUT' || picked.tagName === 'TEXTAREA') {{
            picked.value = '';
          }} else {{
            picked.textContent = '';
          }}
          picked.dispatchEvent(new InputEvent('input', {{
            bubbles: true,
            inputType: 'deleteContentBackward',
            data: null
          }}));
          picked.dispatchEvent(new Event('change', {{ bubbles: true }}));
          return {{ found: true, ...center(picked) }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def _recipient_field_contains(cdp: CDPClient, phone: str) -> bool:
    digits = _normalize_digits(phone)
    return bool(
        cdp.evaluate(
            f"""
            (() => {{
              const digits = {json.dumps(digits)};
              const normalize = (s) => String(s || '').replace(/\\D+/g, '');
              {_visible_helper_js()}
              const selectors = 'input, textarea, [contenteditable="true"], [role="textbox"]';
              for (const el of document.querySelectorAll(selectors)) {{
                if (!visible(el)) continue;
                const value = normalize(el.value || el.innerText || el.textContent || '');
                if (value.includes(digits)) return true;
              }}
              return false;
            }})()
            """,
            timeout_s=3.0,
        )
    )


def enter_phone_number(cdp: CDPClient, args: argparse.Namespace, phone: str) -> None:
    deadline = time.monotonic() + (args.action_timeout_ms / 1000)
    info: dict[str, Any] = {"found": False}
    while time.monotonic() < deadline:
        info = _focus_and_clear_recipient_input(cdp)
        if info.get("found"):
            break
        time.sleep(0.25)

    if not info.get("found"):
        fail_with_debug(cdp, args, "recipient_input_not_found", "전화번호 입력창을 찾지 못했습니다.")

    _click_point(cdp, float(info["x"]), float(info["y"]))
    _insert_text(cdp, phone)

    verify_deadline = time.monotonic() + 5
    while time.monotonic() < verify_deadline:
        if _recipient_field_contains(cdp, phone):
            print(f"[Step 2] 전화번호 입력 완료: {phone!r}")
            return
        time.sleep(0.2)

    fail_with_debug(
        cdp,
        args,
        "recipient_input_verify_failed",
        "전화번호를 입력했지만 화면에서 입력값을 확인하지 못했습니다.",
    )


def _find_contact_result(cdp: CDPClient, phone: str) -> dict[str, Any]:
    digits = _normalize_digits(phone)
    return cdp.evaluate(
        f"""
        (() => {{
          const digits = {json.dumps(digits)};
          const normalizeDigits = (s) => String(s || '').replace(/\\D+/g, '');
          {_visible_helper_js()}
          const wanted = [digits, digits.slice(-10), digits.slice(-8)]
            .filter((v, i, arr) => v.length >= 7 && arr.indexOf(v) === i);

          for (const row of document.querySelectorAll('[data-e2e-contact-row]')) {{
            if (!visible(row)) continue;
            const nameEl = row.querySelector('[data-e2e-contact-name]');
            const numberEl = row.querySelector('[data-e2e-contact-number]');
            const name = (nameEl ? nameEl.innerText || nameEl.textContent || '' : '')
              .replace(/\\s+/g, ' ')
              .trim();
            const number = (numberEl ? numberEl.innerText || numberEl.textContent || '' : '')
              .replace(/\\s+/g, ' ')
              .trim();
            const rowText = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ').trim();
            const rowDigits = normalizeDigits(number || rowText);
            if (wanted.some((part) => rowDigits.includes(part))) {{
              return {{ found: true, name, number, text: rowText, ...center(row) }};
            }}
          }}
          return {{ found: false }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def verify_contact_name(
    cdp: CDPClient,
    args: argparse.Namespace,
    expected_name: str,
    phone: str,
) -> None:
    expected = _normalize_name(expected_name)
    deadline = time.monotonic() + CONTACT_VERIFY_TIMEOUT_S
    result: dict[str, Any] = {"found": False}

    while time.monotonic() < deadline:
        result = _find_contact_result(cdp, phone)
        if result.get("found"):
            break
        time.sleep(0.15)

    if not result.get("found"):
        raise GoogleMessageError(
            f"연락처 이름 확인 실패: 전화번호 {phone!r}에 해당하는 연락처 결과가 없습니다."
        )

    actual = _normalize_name(str(result.get("name") or ""))
    if actual != expected:
        raise GoogleMessageError(
            f"연락처 이름 불일치: 기대값={expected!r}, 화면값={actual!r}, 전화번호={phone!r}"
        )

    print(f"[Step 2] 연락처 이름 확인 완료: {actual!r}")


def _find_phone_candidate(cdp: CDPClient, phone: str) -> dict[str, Any]:
    digits = _normalize_digits(phone)
    return cdp.evaluate(
        f"""
        (() => {{
          const digits = {json.dumps(digits)};
          const normalize = (s) => String(s || '').replace(/\\D+/g, '');
          {_visible_helper_js()}
          const wanted = [digits, digits.slice(-10), digits.slice(-8)]
            .filter((v, i, arr) => v.length >= 7 && arr.indexOf(v) === i);
          const selectors = [
            'button',
            'a',
            '[role="option"]',
            '[role="listitem"]',
            '[role="menuitem"]',
            'li',
            'mat-option',
            '.mat-mdc-option',
            'mws-contact-list-item',
            'mws-contact-row'
          ].join(',');
          for (const el of document.querySelectorAll(selectors)) {{
            if (!visible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim();
            const textDigits = normalize(text);
            if (!textDigits) continue;
            if (wanted.some((part) => textDigits.includes(part))) {{
              return {{ found: true, text, ...center(el) }};
            }}
          }}
          return {{ found: false }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def _find_send_to_number_button(cdp: CDPClient, phone: str) -> dict[str, Any]:
    digits = _normalize_digits(phone)
    return cdp.evaluate(
        f"""
        (() => {{
          const digits = {json.dumps(digits)};
          const normalize = (s) => String(s || '').replace(/\\D+/g, '');
          const sendRe = new RegExp({_js_regex(SEND_TO_PATTERN)}, 'i');
          {_visible_helper_js()}
          const wanted = [digits, digits.slice(-10), digits.slice(-8)]
            .filter((v, i, arr) => v.length >= 7 && arr.indexOf(v) === i);

          const score = (el) => {{
            if (!visible(el)) return -1;
            const text = [
              el.innerText || '',
              el.textContent || '',
              el.getAttribute('aria-label') || '',
              el.getAttribute('title') || ''
            ].join(' ').replace(/\\s+/g, ' ').trim();
            const textDigits = normalize(text);
            if (!wanted.some((part) => textDigits.includes(part))) return -1;
            const hasE2e = el.hasAttribute('data-e2e-send-to-button') ? 100 : 0;
            const hasSendText = sendRe.test(text) ? 20 : 0;
            return hasE2e + hasSendText + Math.min(textDigits.length, 20);
          }};

          const selectors = [
            '[data-e2e-send-to-button]',
            'button',
            'a',
            '[role="button"]',
            '[role="option"]',
            '[role="listitem"]',
            'li',
            'mat-option',
            '.mat-mdc-option',
            'mws-contact-list-item',
            'mws-contact-row'
          ].join(',');
          let best = null;
          let bestScore = -1;
          for (const el of document.querySelectorAll(selectors)) {{
            const s = score(el);
            if (s > bestScore) {{
              best = el;
              bestScore = s;
            }}
          }}
          if (!best || bestScore < 0) return {{ found: false }};
          const text = (best.innerText || best.textContent || best.getAttribute('aria-label') || '')
            .replace(/\\s+/g, ' ')
            .trim();
          best.setAttribute('data-codex-send-to-target', 'true');
          return {{
            found: true,
            text,
            score: bestScore,
            selector: best.hasAttribute('data-e2e-send-to-button') ? 'data-e2e-send-to-button' : '',
            ...center(best)
          }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def _click_send_to_number_with_dom(cdp: CDPClient) -> bool:
    return bool(
        cdp.evaluate(
            """
            (() => {
              const el = document.querySelector('[data-codex-send-to-target="true"]');
              if (!el) return false;
              el.click();
              return true;
            })()
            """,
            timeout_s=5.0,
        )
    )


def _composer_visible(cdp: CDPClient) -> bool:
    return bool(
        cdp.evaluate(
            f"""
            (() => {{
              const re = new RegExp({_js_regex(COMPOSER_PATTERN)}, 'i');
              {_visible_helper_js()}
              const selectors = [
                'input',
                'textarea',
                '[contenteditable="true"]',
                '[role="textbox"]'
              ].join(',');
              for (const el of document.querySelectorAll(selectors)) {{
                if (!visible(el)) continue;
                const label = [
                  el.getAttribute('aria-label') || '',
                  el.getAttribute('placeholder') || '',
                  el.getAttribute('title') || '',
                  el.innerText || '',
                  el.textContent || ''
                ].join(' ');
                if (re.test(label)) return true;
              }}
              return false;
            }})()
            """,
            timeout_s=3.0,
        )
    )


def _find_message_composer(cdp: CDPClient) -> dict[str, Any]:
    return cdp.evaluate(
        f"""
        (() => {{
          const re = new RegExp({_js_regex(COMPOSER_PATTERN)}, 'i');
          {_visible_helper_js()}
          const preferred = document.querySelector('[data-e2e-message-input-box]');
          if (preferred && visible(preferred)) {{
            return {{
              found: true,
              selector: 'data-e2e-message-input-box',
              value: preferred.value || preferred.innerText || preferred.textContent || '',
              ...center(preferred)
            }};
          }}
          const selectors = [
            'textarea',
            'input',
            '[contenteditable="true"]',
            '[role="textbox"]'
          ].join(',');
          for (const el of document.querySelectorAll(selectors)) {{
            if (!visible(el)) continue;
            const label = [
              el.getAttribute('aria-label') || '',
              el.getAttribute('placeholder') || '',
              el.getAttribute('title') || '',
              el.innerText || '',
              el.textContent || ''
            ].join(' ');
            if (re.test(label)) {{
              return {{
                found: true,
                selector: '',
                value: el.value || el.innerText || el.textContent || '',
                ...center(el)
              }};
            }}
          }}
          return {{ found: false }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def _focus_and_clear_message_composer(cdp: CDPClient) -> dict[str, Any]:
    return cdp.evaluate(
        f"""
        (() => {{
          const re = new RegExp({_js_regex(COMPOSER_PATTERN)}, 'i');
          {_visible_helper_js()}
          const candidates = [
            ...document.querySelectorAll('[data-e2e-message-input-box]'),
            ...document.querySelectorAll('textarea, input, [contenteditable="true"], [role="textbox"]')
          ];
          for (const el of candidates) {{
            if (!visible(el)) continue;
            const label = [
              el.getAttribute('aria-label') || '',
              el.getAttribute('placeholder') || '',
              el.getAttribute('title') || '',
              el.innerText || '',
              el.textContent || ''
            ].join(' ');
            if (!el.hasAttribute('data-e2e-message-input-box') && !re.test(label)) continue;
            el.focus();
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {{
              el.value = '';
            }} else {{
              el.textContent = '';
            }}
            el.dispatchEvent(new InputEvent('input', {{
              bubbles: true,
              inputType: 'deleteContentBackward',
              data: null
            }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return {{ found: true, ...center(el) }};
          }}
          return {{ found: false }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def _composer_contains_message(cdp: CDPClient, message: str) -> bool:
    return bool(
        cdp.evaluate(
            f"""
            (() => {{
              const expected = {json.dumps(message)};
              const el = document.querySelector('[data-e2e-message-input-box]');
              if (el) {{
                return (el.value || el.innerText || el.textContent || '') === expected;
              }}
              const selectors = 'textarea, input, [contenteditable="true"], [role="textbox"]';
              for (const field of document.querySelectorAll(selectors)) {{
                const value = field.value || field.innerText || field.textContent || '';
                if (value === expected) return true;
              }}
              return false;
            }})()
            """,
            timeout_s=3.0,
        )
    )


def _composer_is_empty(cdp: CDPClient) -> bool:
    return bool(
        cdp.evaluate(
            """
            (() => {
              const el = document.querySelector('[data-e2e-message-input-box]');
              if (!el) return false;
              return !(el.value || el.innerText || el.textContent || '').trim();
            })()
            """,
            timeout_s=3.0,
        )
    )


def _find_send_message_button(cdp: CDPClient) -> dict[str, Any]:
    return cdp.evaluate(
        f"""
        (() => {{
          {_visible_helper_js()}
          const selectors = [
            '[data-e2e-send-text-button]',
            'button[aria-label*="전송"]',
            'button[aria-label*="Send" i]',
            'button'
          ].join(',');
          for (const el of document.querySelectorAll(selectors)) {{
            if (!visible(el)) continue;
            const text = [
              el.innerText || '',
              el.textContent || '',
              el.getAttribute('aria-label') || '',
              el.getAttribute('title') || ''
            ].join(' ').replace(/\\s+/g, ' ').trim();
            if (el.hasAttribute('data-e2e-send-text-button') || /전송|send/i.test(text)) {{
              return {{
                found: true,
                text,
                disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                selector: el.hasAttribute('data-e2e-send-text-button') ? 'data-e2e-send-text-button' : '',
                ...center(el)
              }};
            }}
          }}
          return {{ found: false }};
        }})()
        """,
        timeout_s=5.0,
    ) or {"found": False}


def confirm_recipient(cdp: CDPClient, args: argparse.Namespace, phone: str) -> None:
    deadline = time.monotonic() + min(4.0, args.action_timeout_ms / 1000)
    clicked_candidate = False

    while time.monotonic() < deadline:
        info = _find_phone_candidate(cdp, phone)
        if info.get("found"):
            _click_point(cdp, float(info["x"]), float(info["y"]))
            clicked_candidate = True
            break
        time.sleep(0.25)

    if not clicked_candidate:
        _press_enter(cdp)

    composer_deadline = time.monotonic() + 12
    while time.monotonic() < composer_deadline:
        if _composer_visible(cdp):
            print("[Step 2] 전화번호 수신자 선택까지 확인했습니다. 메시지는 전송하지 않습니다.")
            return
        time.sleep(0.35)

    fail_with_debug(
        cdp,
        args,
        "recipient_confirm_failed",
        "전화번호 후보를 선택/Enter 했지만 메시지 입력창이 나타나지 않았습니다.",
    )


def step3_click_send_to_number(cdp: CDPClient, args: argparse.Namespace, phone: str) -> None:
    info: dict[str, Any] = {"found": False}
    deadline = time.monotonic() + (args.action_timeout_ms / 1000)
    while time.monotonic() < deadline:
        info = _find_send_to_number_button(cdp, phone)
        if info.get("found"):
            break
        time.sleep(0.25)

    if not info.get("found"):
        fail_with_debug(
            cdp,
            args,
            "send_to_number_button_not_found",
            f"'{phone} 번으로 보내기' 버튼을 찾지 못했습니다.",
        )

    _click_point(cdp, float(info["x"]), float(info["y"]))
    composer_deadline = time.monotonic() + 5
    while time.monotonic() < composer_deadline:
        if _composer_visible(cdp):
            print(f"[Step 3] '{info.get('text') or phone}' 버튼을 클릭했습니다.")
            return
        time.sleep(0.25)

    if _click_send_to_number_with_dom(cdp):
        composer_deadline = time.monotonic() + 8
        while time.monotonic() < composer_deadline:
            if _composer_visible(cdp):
                print(f"[Step 3] '{info.get('text') or phone}' 버튼을 클릭했습니다. (DOM click fallback)")
                return
            time.sleep(0.25)

    fail_with_debug(
        cdp,
        args,
        "send_to_number_click_failed",
        "'~번으로 보내기' 버튼을 클릭했지만 메시지 입력창이 나타나지 않았습니다.",
    )


def step4_type_and_send_message(cdp: CDPClient, args: argparse.Namespace, message: str) -> None:
    composer_deadline = time.monotonic() + (args.action_timeout_ms / 1000)
    composer: dict[str, Any] = {"found": False}
    while time.monotonic() < composer_deadline:
        composer = _focus_and_clear_message_composer(cdp)
        if composer.get("found"):
            break
        time.sleep(0.25)

    if not composer.get("found"):
        fail_with_debug(
            cdp,
            args,
            "message_composer_not_found",
            "메시지 입력창을 찾지 못했습니다.",
        )

    _click_point(cdp, float(composer["x"]), float(composer["y"]))
    _insert_text(cdp, message)

    verify_deadline = time.monotonic() + 5
    while time.monotonic() < verify_deadline:
        if _composer_contains_message(cdp, message):
            print(f"[Step 4] 메시지 입력 완료: {message!r}")
            break
        time.sleep(0.2)
    else:
        fail_with_debug(
            cdp,
            args,
            "message_input_verify_failed",
            "메시지를 입력했지만 입력창에서 본문을 확인하지 못했습니다.",
        )

    send_button_deadline = time.monotonic() + (args.action_timeout_ms / 1000)
    send_button: dict[str, Any] = {"found": False}
    while time.monotonic() < send_button_deadline:
        send_button = _find_send_message_button(cdp)
        if send_button.get("found") and not send_button.get("disabled"):
            break
        time.sleep(0.25)

    if not send_button.get("found"):
        fail_with_debug(
            cdp,
            args,
            "send_message_button_not_found",
            "메시지 전송 버튼을 찾지 못했습니다.",
        )
    if send_button.get("disabled"):
        fail_with_debug(
            cdp,
            args,
            "send_message_button_disabled",
            "메시지 전송 버튼이 비활성 상태입니다.",
        )

    _click_point(cdp, float(send_button["x"]), float(send_button["y"]))

    sent_deadline = time.monotonic() + 12
    while time.monotonic() < sent_deadline:
        if _composer_is_empty(cdp):
            print("[Step 4] 메시지 전송 완료.")
            return
        time.sleep(0.25)

    fail_with_debug(
        cdp,
        args,
        "message_send_verify_failed",
        "전송 버튼을 클릭했지만 메시지 입력창이 비워지는 것을 확인하지 못했습니다.",
    )


def step2_start_chat_and_phone(
    cdp: CDPClient,
    args: argparse.Namespace,
    expected_name: Optional[str],
    phone: str,
) -> None:
    if _new_conversation_visible(cdp):
        print("[Step 2] 이미 채팅 시작 화면입니다. 버튼 클릭은 생략합니다.")
    else:
        click_start_chat(cdp, args)
        time.sleep(0.5)
    enter_phone_number(cdp, args, phone)
    if expected_name:
        verify_contact_name(cdp, args, expected_name, phone)
    else:
        print("[Step 2] 이름 입력이 없어 연락처 이름 검증을 생략합니다.")
    print("[Step 2] 전화번호 입력까지 완료했습니다.")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open Google Messages Web in real Chrome, click Start chat, "
            "optionally verify a contact name, enter a phone number, and send a message."
        )
    )
    parser.add_argument(
        "values",
        nargs="*",
        help="입력값. 형식: [이름] 전화번호 메시지",
    )
    parser.add_argument("--name", dest="name_option", help="기대하는 연락처 이름.")
    parser.add_argument("--phone", dest="phone_option", help="입력할 전화번호.")
    parser.add_argument("--message", dest="message_option", help="보낼 메시지.")
    parser.add_argument("--url", default=MESSAGES_URL, help=f"열 URL. 기본값: {MESSAGES_URL}")
    parser.add_argument("--port", type=int, default=DEFAULT_DEBUG_PORT, help="Chrome CDP 포트.")
    parser.add_argument(
        "--attach-only",
        action="store_true",
        help="Chrome을 새로 실행하지 않고 이미 열린 CDP Chrome에만 연결합니다.",
    )
    parser.add_argument("--chrome-executable", help="Google Chrome 실행 파일 경로.")
    parser.add_argument(
        "--user-data-dir",
        help=f"Chrome 전용 프로필 경로. 기본값: {DEFAULT_PROFILE_DIR}",
    )
    parser.add_argument(
        "--profile-directory",
        help='Chrome profile-directory 값. 예: "Default", "Profile 1"',
    )
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=DEFAULT_LOGIN_TIMEOUT_S,
        help="로그인/페어링 및 Start chat 버튼 대기 시간(초).",
    )
    parser.add_argument(
        "--action-timeout-ms",
        type=int,
        default=DEFAULT_ACTION_TIMEOUT_MS,
        help="버튼 클릭/입력 동작 타임아웃(ms).",
    )
    parser.add_argument(
        "--fill-only",
        action="store_true",
        help="Step 2(전화번호 입력)까지만 수행하고 Step 3 '~번으로 보내기' 클릭은 생략합니다.",
    )
    parser.add_argument(
        "--confirm-recipient",
        action="store_true",
        help="호환용 옵션입니다. 기본 동작이 이미 Step 3 수신자 선택까지 수행합니다.",
    )
    parser.add_argument(
        "--debug-dir",
        default=str(Path.cwd() / "google_message_debug"),
        help="실패 시 screenshot/html 저장 폴더.",
    )

    args = parser.parse_args(argv)
    values = list(args.values)
    if len(values) > 3:
        parser.error("positional 인자는 최대 3개입니다: [이름] 전화번호 메시지")

    name = args.name_option
    phone = args.phone_option
    message = args.message_option

    if phone is None:
        if values:
            first = values.pop(0)
            if name is None and _looks_like_phone(first):
                phone = first
            elif name is None:
                name = first
                if values:
                    phone = values.pop(0)
            else:
                phone = first
    elif name is None and values and not _looks_like_phone(values[0]) and message is not None:
        name = values.pop(0)

    if message is None and values:
        message = values.pop(0)

    if values:
        parser.error("남는 positional 인자가 있습니다. 형식: [이름] 전화번호 메시지")

    if name is None and phone is None:
        maybe_name = input("이름(선택, 없으면 Enter): ").strip()
        name = maybe_name or None

    args.name = _normalize_name(name) if name else None
    args.phone = phone
    args.message = message

    if not args.phone:
        args.phone = input("전화번호: ").strip()
    if not args.phone.strip():
        parser.error("전화번호가 비어 있습니다.")
    if len(_normalize_digits(args.phone)) < 7:
        parser.error("전화번호 숫자가 너무 짧습니다.")
    if not args.fill_only and args.message is None:
        args.message = input("메시지: ").strip()
    if args.message is not None and not args.message.strip():
        parser.error("메시지가 비어 있습니다.")
    return args


def run(args: argparse.Namespace) -> int:
    ensure_chrome_cdp(args)
    target = _get_or_create_target(args.port, args.url)
    already_open = _is_messages_target(target)
    _activate_target(args.port, target.get("id", ""))

    cdp = CDPClient(target["webSocketDebuggerUrl"])
    try:
        if already_open:
            use_existing_messages_page(cdp, args)
        else:
            step1_open_messages(cdp, args)
        step2_start_chat_and_phone(
            cdp,
            args,
            args.name.strip() if args.name else None,
            args.phone.strip(),
        )
        if not args.fill_only:
            step3_click_send_to_number(cdp, args, args.phone.strip())
            if args.message is not None:
                step4_type_and_send_message(cdp, args, args.message)
                print("[완료] Step 1~4 성공.")
            else:
                print("[완료] Step 1~3 성공.")
        else:
            print("[완료] Step 1~2 성공.")
    finally:
        cdp.close()

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = parse_args(argv)
        return run(args)
    except KeyboardInterrupt:
        print("\n[중단] 사용자 입력으로 종료했습니다.", file=sys.stderr)
        return 130
    except GoogleMessageError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
