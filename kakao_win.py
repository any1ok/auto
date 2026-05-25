"""카카오톡 자동화 (Windows 전용).

Step 1 — 이미 실행 중인 카카오톡 메인 창을 foreground 로
Step 2 — 친구(1) / 채팅(2) / 더보기(3) 탭으로 포커스
Step 3 — 현재 탭 상단 검색창에 텍스트 입력 (Enter 미입력)
Step 4/5/6 — 검색 결과를 ↓/Enter 로 하나씩 열어 채팅창 타이틀로 매칭 검증
            (불일치면 ESC 로 즉시 닫고 다음 결과 시도)
Step 7 — 열린 채팅방의 RichEdit 입력창에 메시지를 WM_SETTEXT 로 채우고
         VK_RETURN PostMessage 로 전송 (전송 검증 = WM_GETTEXTLENGTH → 0)

mac.md / kakao_mac.py 의 step 구조는 공유하되, 구현은 macOS 의 osascript
대신 Win32 API (user32 / kernel32) 를 ctypes 로 직접 호출한다. 외부
라이브러리 의존성 없음.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import platform
import sys
import time
from pathlib import Path
from typing import Optional


# 진단 출력에 한글이 섞이고 일부 라인은 ASCII 외 기호도 들어가는데, Windows
# 콘솔이 기본 cp949 (한글) / cp437 (영문) 으로 잡혀 있으면 stdout 인코딩이
# 'strict' 라 인코딩 불가 문자가 나오는 순간 UnicodeEncodeError 로 죽는다.
# Python 3.7+ 의 reconfigure 로 stdout / stderr 를 UTF-8 + backslashreplace
# 로 바꿔, 인코딩 에러 대신 디버깅용 escape 출력으로 떨어지게 한다.
# Windows 콘솔이 chcp 65001 로 잡혀 있으면 한글까지 그대로 보인다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError):
        # 리다이렉트 / 파이프 / 구버전 Python 등은 그냥 패스.
        pass


KAKAO_PROCESS_NAME = "KakaoTalk.exe"
# 윈도우 타이틀 후보 — 한글/영문 OS, 일부 빌드 차이를 함께 커버.
KAKAO_WINDOW_TITLES = ("카카오톡", "KakaoTalk")

# Step 2 탭 선택. Mac (mac.py) 은 1=친구 / 2=채팅 만이지만 카톡 PC 는
# 사이드바에 친구 / 채팅 / 더보기 3 탭이 있고 Ctrl+Tab 으로 순환한다.
TAB_FRIENDS = "1"
TAB_CHATS = "2"
TAB_MORE = "3"
TAB_CHOICES = (TAB_FRIENDS, TAB_CHATS, TAB_MORE)
TAB_LABELS = {TAB_FRIENDS: "친구", TAB_CHATS: "채팅", TAB_MORE: "더보기"}

# Step 2 탭 컨테이너 클래스명 (Spy++ 로 확인된 카톡 PC 구조).
# 메인 #32770 → EVA_ChildWindow → EVA_Window N 개 (정확히 1 개만 visible).
KAKAO_CHILD_CLASS = "EVA_ChildWindow"
KAKAO_PANEL_CLASS = "EVA_Window"

# Step 3 검색창 컨트롤 클래스명. 카톡 PC 의 각 EVA_Window 패널 직속 자식
# 으로 표준 Win32 Edit 컨트롤이 1 개 있다 (RichEdit 아님 — RichEdit50W 은
# 채팅방 메시지 입력란용). 표준 Edit 이라 SendMessageW(WM_SETTEXT) 가
# 그대로 먹고, 자체 EN_CHANGE 통지를 부모로 보내 카톡이 검색을 트리거한다.
KAKAO_EDIT_CLASS = "Edit"

# Step 4/5/6 — 검색 결과 리스트 컨트롤 클래스명. 각 EVA_Window 패널 안에는
# EVA_VH_ListControl_Dblclk 가 두 개 있다 (직접 진단으로 확인):
#   - title='ChatRoomListCtrl_*' visible=False 일 때 = 평소 채팅 목록 (검색 안 함)
#   - title='SearchListCtrl_*'   visible=True  일 때 = 검색 결과 리스트
# 검색 중에는 SearchListCtrl 가 visible, ChatRoomListCtrl 가 hidden 으로
# 토글된다. ↓ (VK_DOWN) 를 Edit 에 PostMessage 하면 single-line Edit 이
# 그냥 먹어버리기 때문에 검색결과 하이라이트가 안 움직이는데, 이 SearchListCtrl
# hwnd 에 직접 PostMessage 하면 리스트 컨트롤이 직접 처리해 다음 row 로
# 하이라이트를 옮긴다. (Enter 는 Edit 이 부모로 forward 해 줘 잘 동작.)
KAKAO_LIST_CTRL_CLASS = "EVA_VH_ListControl_Dblclk"
# 검색 결과 리스트의 title 접두사. 채팅 목록 리스트의 title 접두사와 구분.
KAKAO_SEARCH_LIST_TITLE_PREFIX = "SearchListCtrl"

# foreground 전환 폴링 (mac.md 의 frontmost 폴링과 같은 방식).
FOREGROUND_TIMEOUT_S = 1.5
FOREGROUND_POLL_INTERVAL_S = 0.04

# Step 2: Ctrl+Tab 한 번 보낸 뒤 visible 상태 갱신 대기 / 폴링 간격 /
# 최대 시도 횟수. 도달 못 하면 진단 + 에러 (무한 루프 방지).
TAB_SWITCH_AFTER_PRESS_S = 0.08
TAB_SWITCH_POLL_INTERVAL_S = 0.06
TAB_SWITCH_VERIFY_TIMEOUT_S = 0.4
TAB_SWITCH_MAX_PRESSES = 8

# ShowWindow nCmdShow 값.
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_RESTORE = 9

# OpenProcess 권한 — Vista+ 에서 일반 사용자가 다른 프로세스의 이미지명 조회용.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# CreateToolhelp32Snapshot 플래그 / 상수.
TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# SendInput 상수.
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0
VK_CONTROL = 0x11
VK_TAB = 0x09

# Step 3 SendMessage 메시지 ID. WM_SETTEXT 의 반환값은 1=성공 / 0=실패
# (Edit 컨트롤이 메모리 할당에 실패하거나 UIPI 로 차단된 경우 등).
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E

# Step 7 — 채팅창의 메시지 입력 RichEdit 컨트롤 클래스 후보.
# 카톡 PC 의 입력란은 표준 Win32 Edit 이 아니라 RichEdit 컨트롤이다. 정확한
# 클래스명은 카톡 빌드 / RichEdit 버전에 따라 달라서 여러 레퍼런스가 서로 다른
# 이름을 기록하고 있다:
#   - RichEdit50W : 최근(2020~) 빌드. 가장 흔함
#     (ssam2s.tistory.com/9, Xenia101/KakaoTalk-python)
#   - RichEdit20W : 구버전 빌드 (airfox1.tistory.com/5,
#     oppadu.com 의 엑셀-카톡 자동화 매크로가 명시적으로 fallback)
# 둘 다 시도하고, 그래도 못 찾으면 마지막으로 재귀 enumerate 해서
# 'RichEdit' 로 시작하는 후손 클래스 중 하나를 찾는 식의 안전 fallback.
KAKAO_MSG_EDIT_CLASSES = ("RichEdit50W", "RichEdit20W")
KAKAO_MSG_EDIT_CLASS_PREFIX = "RichEdit"

# Step 7 — Enter 전송 후 "정말로 전송됐는지" 검증용 폴링. 카톡이 메시지를
# 큐에 넣은 직후 RichEdit 내용이 원본 메시지에서 다른 상태로 바뀐다 (보통
# 비어 있거나 placeholder 텍스트 '메시지 입력' 으로 토글). length == 0 만
# 보는 단순 검증은 placeholder 때문에 오작동하므로 **'현재 텍스트가 우리가
# 보낸 메시지와 같은가'** 로 판정한다. UI 갱신은 비동기라 짧은 폴링 필요.
MSG_VERIFY_TIMEOUT_S = 2.0
MSG_VERIFY_POLL_INTERVAL_S = 0.05

# Step 7 — Ctrl+V 전후 RichEdit 내용 갱신 대기. SendInput 으로 Ctrl+V 를
# 보낸 직후 RichEdit 이 paste 한 텍스트로 채워지는 데 잠시 걸린다 (특히
# 첫 호출은 클립보드 매니저 / IME / RichEdit 의 EN_PASTE 처리에 ms 단위
# 지연). paste 검증 폴링용.
PASTE_VERIFY_TIMEOUT_S = 1.0
PASTE_VERIFY_POLL_INTERVAL_S = 0.03

# 클립보드 / 메모리 상수.
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# 가상 키.
VK_V = ord('V')
VK_A = ord('A')
VK_T = ord('T')

# 표준 파일 열기 다이얼로그 / 버튼 메시지.
BM_CLICK = 0x00F5
FILE_DIALOG_TITLES = ("열기", "Open")
FILE_DIALOG_TIMEOUT_S = 6.0
FILE_SEND_PREVIEW_TIMEOUT_S = 8.0
FILE_SEND_CLOSE_TIMEOUT_S = 10.0
FILE_SEND_POLL_INTERVAL_S = 0.05

# Step 4/5/6 통합용 — 검색 결과를 하나씩 열어 채팅창 타이틀로 매칭 검증.
# 모디파이어 없는 단일키(VK_RETURN/VK_DOWN/VK_ESCAPE) 는 PostMessage 로 비활성
# hwnd 에 그대로 보내도 카톡이 받아준다 (ssam2s.tistory.com/9, airfox1.tistory.com/5
# 의 검증된 패턴). Step 2 의 Ctrl+Tab PostMessage 금지 노트는 modifier+key 의
# 시스템 키보드 상태 갱신 이슈에만 해당.
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
VK_DOWN = 0x28
VK_ESCAPE = 0x1B  # 카톡 공식 단축키: 채팅방 닫기 (cs.kakao.com/helps_html/1073183088)

# 한 번의 시도 = Enter 로 현재 하이라이트된 결과 열기 → 타이틀 검증 → 불일치면
# ESC 로 즉시 닫기 → ↓ 로 하이라이트 다음 칸 이동. 사용자가 알아채기 전에
# 빠르게 빠져나오기 위해 짧은 폴링 타임아웃을 쓴다.
OPEN_MAX_ATTEMPTS = 10
# Step 3 의 WM_SETTEXT 직후 카톡이 비동기로 결과 리스트를 갱신할 시간 필요.
# airfox1.tistory.com/5 의 검증된 예제도 WM_SETTEXT 후 time.sleep(1) 을
# 안정성용으로 명시. 채팅 탭은 메시지 본문까지 인덱스 검색이라 더 느린 경우가
# 있어 친구탭(빠름) 대비 여유 있게 1.0 s 로 잡는다.
OPEN_VERIFY_INITIAL_DELAY_S = 1.0
OPEN_VERIFY_POLL_INTERVAL_S = 0.1
OPEN_VERIFY_TIMEOUT_S = 1.5
CLOSE_VERIFY_TIMEOUT_S = 0.5
# 리스트 끝(↓ 가 더 안 내려감) 감지: 같은 title 이 연속 N 회 나오면 = 같은 방이
# 재오픈되고 있다 = ↓ 가 하이라이트를 이동시키지 못함 → 더 시도해도 무의미.
SAME_TITLE_BOTTOM_RUN = 3


class KakaoWinError(Exception):
    """카카오톡 자동화 중 발생하는 오류."""


def _ensure_windows() -> None:
    if platform.system() != "Windows":
        raise KakaoWinError(f"Windows 전용입니다. 현재 OS: {platform.system()}")


# ---------------------------------------------------------------------------
# Win32 바인딩
# ---------------------------------------------------------------------------

class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),  # ULONG_PTR
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


# EnumWindows / EnumChildWindows 콜백 시그니처. Win32 콜백은 stdcall 이라
# WINFUNCTYPE 사용 (CFUNCTYPE 은 cdecl 이라 스택이 어긋남).
_EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


# SendInput 구조체 — INPUT 의 union 안에 KEYBDINPUT / MOUSEINPUT / HARDWAREINPUT
# 세 가지가 모두 들어갈 수 있어야 한다. 키보드만 보낼 거라도 union 전체 sizeof
# 가 INPUT sizeof 에 정확히 반영되어야 cbSize (32-bit: 28, 64-bit: 40) 가 맞아
# SendInput 이 0 을 반환하며 silent 실패하는 사고를 피할 수 있다.

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),  # ULONG_PTR
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),  # ULONG_PTR
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wt.DWORD),
        ("u", _INPUT_UNION),
    ]


_user32: Optional[ctypes.WinDLL] = None
_kernel32: Optional[ctypes.WinDLL] = None


def _load_win32() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """user32 / kernel32 를 한 번만 로드하고 argtypes/restype 을 지정."""
    global _user32, _kernel32
    if _user32 is not None and _kernel32 is not None:
        return _user32, _kernel32

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.EnumWindows.argtypes = [_EnumWindowsProc, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wt.HWND
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.BringWindowToTop.restype = wt.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.AttachThreadInput.restype = wt.BOOL
    # cross-thread SetFocus 우회용. AttachThreadInput 으로 입력 큐를 묶은 뒤
    # SetFocus 하면 다른 프로세스 윈도우에도 포커스 이동 가능. Step 7 의 Enter
    # SendInput 이 정확히 메시지 입력 RichEdit 으로 가게 하는 데 필요.
    user32.SetFocus.argtypes = [wt.HWND]
    user32.SetFocus.restype = wt.HWND
    user32.GetFocus.argtypes = []
    user32.GetFocus.restype = wt.HWND
    user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowExW.restype = wt.HWND
    user32.EnumChildWindows.argtypes = [wt.HWND, _EnumWindowsProc, wt.LPARAM]
    user32.EnumChildWindows.restype = wt.BOOL
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetParent.argtypes = [wt.HWND]
    user32.GetParent.restype = wt.HWND
    user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
    user32.MapVirtualKeyW.restype = wt.UINT
    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    user32.SendInput.restype = wt.UINT
    # SendMessageW 의 LRESULT 는 ctypes.wintypes 에 없어서 c_ssize_t 로
    # 직접 지정 (포인터 폭과 같음 — 32/64 bit 자동 대응).
    # lParam 은 LPCWSTR (c_wchar_p) 로 받아 한글 wide string 을 그대로 전달.
    user32.SendMessageW.argtypes = [
        wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    # PostMessageW 는 비활성 hwnd 에도 메시지를 큐잉할 수 있어 Enter/↓/ESC
    # 처럼 modifier 가 없는 키 입력을 검색 Edit / 채팅창에 그대로 보낼 때 쓴다.
    user32.PostMessageW.argtypes = [
        wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
    ]
    user32.PostMessageW.restype = wt.BOOL
    # Step 7 — 클립보드 API. Ctrl+V 로 메시지를 paste 하려면 먼저 클립보드에
    # 우리 텍스트를 set 해야 한다. CF_UNICODETEXT (UTF-16) 만 사용.
    user32.OpenClipboard.argtypes = [wt.HWND]
    user32.OpenClipboard.restype = wt.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wt.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wt.BOOL
    user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
    user32.SetClipboardData.restype = wt.HANDLE
    user32.GetClipboardData.argtypes = [wt.UINT]
    user32.GetClipboardData.restype = wt.HANDLE

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wt.BOOL
    kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wt.BOOL
    # Step 7 — 클립보드용 글로벌 메모리. SetClipboardData(CF_UNICODETEXT, hmem)
    # 의 hmem 은 GMEM_MOVEABLE 로 GlobalAlloc 한 핸들이어야 하고, 호출 후
    # ownership 이 클립보드로 넘어가서 우리가 GlobalFree 하면 안 된다.
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wt.HANDLE
    kernel32.GlobalLock.argtypes = [wt.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
    kernel32.GlobalUnlock.restype = wt.BOOL
    kernel32.GlobalSize.argtypes = [wt.HANDLE]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    _user32 = user32
    _kernel32 = kernel32
    return user32, kernel32


# ---------------------------------------------------------------------------
# 프로세스 / 윈도우 조회
# ---------------------------------------------------------------------------

def _get_process_image_name(pid: int) -> str:
    """PID 로 실행 파일 basename 을 얻는다 (실패 시 빈 문자열)."""
    if pid <= 0:
        return ""
    _, kernel32 = _load_win32()
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        # 예: C:\Program Files (x86)\Kakao\KakaoTalk\KakaoTalk.exe → KakaoTalk.exe
        path = buf.value
        return path.rsplit("\\", 1)[-1] if path else ""
    finally:
        kernel32.CloseHandle(h)


def is_kakao_running() -> bool:
    """ToolHelp 스냅샷으로 KakaoTalk.exe 프로세스 존재 여부 확인.

    "메인 창 없음" 과 "프로세스 자체 없음" 을 구별해 더 정확한 에러 메시지를
    내기 위해 사용. (윈도우 enumerate 만으로는 둘을 못 가리는 경우가 있음.)
    """
    _, kernel32 = _load_win32()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    snap_val = ctypes.cast(snap, ctypes.c_void_p).value
    if snap_val is None or snap_val == _INVALID_HANDLE_VALUE:
        return False
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return False
        target = KAKAO_PROCESS_NAME.lower()
        while True:
            if entry.szExeFile.lower() == target:
                return True
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                return False
    finally:
        kernel32.CloseHandle(snap)


def _enum_kakao_windows() -> list[tuple[int, str, bool, bool]]:
    """KakaoTalk.exe 소유의 모든 top-level 윈도우.

    반환: [(hwnd, title, visible, iconic), ...]
    """
    user32, _ = _load_win32()
    results: list[tuple[int, str, bool, bool]] = []
    target_exe = KAKAO_PROCESS_NAME.lower()

    def _callback(hwnd: int, _lparam: int) -> bool:
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _get_process_image_name(pid.value)
        if exe.lower() != target_exe:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        visible = bool(user32.IsWindowVisible(hwnd))
        iconic = bool(user32.IsIconic(hwnd))
        results.append((hwnd, title, visible, iconic))
        return True

    cb = _EnumWindowsProc(_callback)  # 콜백 객체를 GC 되지 않게 유지
    user32.EnumWindows(cb, 0)
    return results


def _pick_main_window(
    kakao_windows: list[tuple[int, str, bool, bool]],
) -> Optional[int]:
    """KakaoTalk.exe 의 top-level 창들 중 "메인 창" 후보 1개 선택.

    우선순위:
      1) 타이틀이 정확히 "카카오톡" / "KakaoTalk" 인 visible 창
      2) 타이틀이 정확 매칭이지만 hidden (트레이로 숨김) 인 창
      3) 그 외 타이틀이 있는 visible 창
      4) 그 외 타이틀이 있는 hidden 창
    """
    title_match = set(KAKAO_WINDOW_TITLES)

    def score(item: tuple[int, str, bool, bool]) -> int:
        _, title, visible, _ = item
        if title in title_match and visible:
            return 4
        if title in title_match:
            return 3
        if title and visible:
            return 2
        if title:
            return 1
        return 0

    ranked = sorted(kakao_windows, key=score, reverse=True)
    if not ranked or score(ranked[0]) == 0:
        return None
    return ranked[0][0]


# ---------------------------------------------------------------------------
# foreground 전환
# ---------------------------------------------------------------------------

def _force_foreground(hwnd: int) -> None:
    """SetForegroundWindow 의 포커스 절도 방지 제한을 AttachThreadInput 으로 우회.

    임의 프로세스가 SetForegroundWindow 를 호출하면 Windows 가 거의 무시한다
    (LockSetForegroundWindow / 포커스 절도 방지). 표준 우회 트릭:
      1) 현재 foreground 창의 스레드와 우리 스레드를 AttachThreadInput
      2) (필요하면) 타겟 창의 스레드도 추가 Attach
      3) BringWindowToTop + SetForegroundWindow
      4) 모든 Attach 를 detach
    """
    user32, kernel32 = _load_win32()

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)

    if user32.GetForegroundWindow() == hwnd:
        return

    cur_tid = kernel32.GetCurrentThreadId()
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = (
        user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
    )
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    attached_fg = False
    attached_target = False
    try:
        if fg_tid and fg_tid != cur_tid:
            attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        if target_tid and target_tid != cur_tid and target_tid != fg_tid:
            attached_target = bool(
                user32.AttachThreadInput(cur_tid, target_tid, True)
            )
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_target:
            user32.AttachThreadInput(cur_tid, target_tid, False)
        if attached_fg:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def wait_for_foreground(
    hwnd: int,
    timeout_s: float = FOREGROUND_TIMEOUT_S,
    interval_s: float = FOREGROUND_POLL_INTERVAL_S,
) -> bool:
    """activate 직후 sleep 대신 GetForegroundWindow 폴링."""
    user32, _ = _load_win32()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(interval_s)
    return False


# ---------------------------------------------------------------------------
# Step 1
# ---------------------------------------------------------------------------

def step1_activate_kakao() -> int:
    """카카오톡 메인 창을 foreground 로. 성공 시 hwnd 반환."""
    windows = _enum_kakao_windows()
    if not windows:
        # 윈도우가 하나도 없는 경우: 프로세스 자체가 없는지 / 메인 창만 닫힌 건지 구별.
        if not is_kakao_running():
            raise KakaoWinError(
                "카카오톡이 실행되어 있지 않습니다. 먼저 카카오톡을 켜주세요."
            )
        raise KakaoWinError(
            "KakaoTalk.exe 는 떠 있는데 top-level 윈도우가 없습니다. "
            "(메인 창이 완전히 닫혔거나 다른 데스크탑에 있을 수 있음)"
        )

    hwnd = _pick_main_window(windows)
    if hwnd is None:
        # 타이틀 있는 창이 하나도 없음 — 트레이 아이콘 등 보조 창만 있는 상태.
        print(
            "[Step 1] KakaoTalk.exe 의 top-level 윈도우 목록 (메인 후보 없음):",
            file=sys.stderr,
        )
        for h, title, visible, iconic in windows:
            print(
                f"  - hwnd=0x{h:08X} title={title!r} "
                f"visible={visible} iconic={iconic}",
                file=sys.stderr,
            )
        raise KakaoWinError(
            "KakaoTalk 메인 창을 찾지 못했습니다. "
            "트레이 아이콘만 떠 있는 상태라면 트레이에서 카카오톡 아이콘을 "
            "한 번 클릭해 메인 창을 띄운 뒤 다시 시도해주세요."
        )

    _force_foreground(hwnd)
    if not wait_for_foreground(hwnd):
        raise KakaoWinError(
            f"카카오톡이 {FOREGROUND_TIMEOUT_S}s 안에 foreground 가 되지 "
            f"않았습니다. (다른 앱이 포커스 절도 방지로 잡고 있거나, "
            f"카카오톡이 관리자 권한으로 실행 중일 수 있습니다.)"
        )

    print("[Step 1] 카카오톡을 포커스했습니다.")
    return hwnd


# ---------------------------------------------------------------------------
# Step 2 — 탭 포커스 (친구 / 채팅 / 더보기)
# ---------------------------------------------------------------------------
#
# 카카오톡 PC 는 mac 의 ⌘+1 / ⌘+2 같은 절대 위치 단축키가 없고 `Ctrl+Tab`
# 으로 친구 → 채팅 → 더보기 → (순환) 토글만 가능하다. 그래서 step 2 는:
#   1) 메인 #32770 의 자식 EVA_ChildWindow 안에 있는 EVA_Window 들을 모은다
#      — 카톡 PC 는 각 탭 패널을 EVA_Window 로 만들어 두고 정확히 한 개만
#      visible 로 토글한다 (Spy++ 분석: ssam2s.tistory.com/9).
#   2) 현재 visible 인 EVA_Window 의 0-indexed 위치 = 현재 활성 탭.
#   3) 목표 탭과 같지 않으면 `Ctrl+Tab` 을 SendInput 으로 1회 보내고 짧게
#      폴링 → 같아질 때까지 반복. 사이클 길이(보통 3) 안에서 도달.
#
# 주의: PostMessage(WM_KEYDOWN, VK_CONTROL/VK_TAB) 로는 modifier state 가
# 시스템에 갱신되지 않아 카톡이 "그냥 Tab" 으로만 인식하는 사례가 많다.
# Step 1 이 이미 카톡을 foreground 로 만들어 두었으므로 SendInput 만 사용.

def _find_kakao_child_window(top_hwnd: int) -> Optional[int]:
    """메인 #32770 직속의 EVA_ChildWindow 한 개를 찾는다 (없으면 None)."""
    user32, _ = _load_win32()
    h = user32.FindWindowExW(top_hwnd, None, KAKAO_CHILD_CLASS, None)
    return h if h else None


def _get_class_name(hwnd: int) -> str:
    user32, _ = _load_win32()
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if n > 0 else ""


def _enum_direct_children(parent_hwnd: int) -> list[int]:
    """EnumChildWindows 는 손자까지 재귀 enumerate 하므로 GetParent 로 직속만 필터.

    반환은 EnumChildWindows 호출 순서 = Z-order. EVA_Window 패널들의 등장
    순서를 시각적 탭 순서(친구→채팅→더보기)로 가정한다.
    """
    user32, _ = _load_win32()
    results: list[int] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        if user32.GetParent(hwnd) == parent_hwnd:
            results.append(hwnd)
        return True

    cb = _EnumWindowsProc(_callback)  # 콜백 객체 GC 방지
    user32.EnumChildWindows(parent_hwnd, cb, 0)
    return results


def _enum_eva_panels(parent_hwnd: int) -> list[tuple[int, bool]]:
    """EVA_ChildWindow 의 직속 자식 중 클래스명이 EVA_Window 인 것 수집.

    반환: [(hwnd, visible), ...] — 등장 순서 = 시각적 탭 순서로 가정.
    """
    user32, _ = _load_win32()
    panels: list[tuple[int, bool]] = []
    for h in _enum_direct_children(parent_hwnd):
        if _get_class_name(h) == KAKAO_PANEL_CLASS:
            panels.append((h, bool(user32.IsWindowVisible(h))))
    return panels


def _current_visible_panel_index(panels: list[tuple[int, bool]]) -> Optional[int]:
    """패널 리스트에서 visible 인 항목의 0-indexed 위치.

    카톡은 항상 정확히 1 개만 visible 이어야 한다. 0 개 또는 2 개 이상이면
    예외 상황(애니메이션 전환 중 등)으로 보고 None.
    """
    visible_idxs = [i for i, (_, v) in enumerate(panels) if v]
    if len(visible_idxs) == 1:
        return visible_idxs[0]
    return None


def _dump_panels_to_stderr(panels: list[tuple[int, bool]], header: str) -> None:
    print(header, file=sys.stderr)
    if not panels:
        print("  (EVA_Window 패널이 하나도 안 잡힘)", file=sys.stderr)
        return
    for i, (h, v) in enumerate(panels):
        print(f"  - idx={i} hwnd=0x{h:08X} visible={v}", file=sys.stderr)


def _ki(vk: int, scan: int, flags: int) -> _INPUT:
    """단일 키 _INPUT 레코드 (KEYBOARD) 생성. Step 2 / Step 7 공용 헬퍼.

    `wScan` 도 MapVirtualKeyW 로 채워 둠 (일부 앱은 wVk 만 보내면 무시).
    """
    ev = _INPUT()
    ev.type = INPUT_KEYBOARD
    ev.ki.wVk = vk
    ev.ki.wScan = scan
    ev.ki.dwFlags = flags
    ev.ki.time = 0
    ev.ki.dwExtraInfo = None
    return ev


def _send_ctrl_tab() -> None:
    """SendInput 으로 Ctrl+Tab 한 번을 batch 전송.

    순서: VK_CONTROL down → VK_TAB down → VK_TAB up → VK_CONTROL up.
    """
    user32, _ = _load_win32()
    ctrl_scan = user32.MapVirtualKeyW(VK_CONTROL, MAPVK_VK_TO_VSC)
    tab_scan = user32.MapVirtualKeyW(VK_TAB, MAPVK_VK_TO_VSC)

    inputs = (_INPUT * 4)(
        _ki(VK_CONTROL, ctrl_scan, 0),
        _ki(VK_TAB, tab_scan, 0),
        _ki(VK_TAB, tab_scan, KEYEVENTF_KEYUP),
        _ki(VK_CONTROL, ctrl_scan, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(4, inputs, ctypes.sizeof(_INPUT))
    if sent != 4:
        err = ctypes.get_last_error()
        raise KakaoWinError(
            f"SendInput 실패 (sent={sent}/4, GetLastError={err}). "
            "다른 프로세스가 입력을 차단하고 있거나 권한이 부족할 수 있습니다."
        )


def _send_vk_sendinput(vk: int) -> None:
    """단일 vk 의 KEYDOWN + KEYUP 을 SendInput 으로 전송.

    PostMessage 와 달리 SendInput 은 **OS 입력 큐** 로 들어가서 WH_KEYBOARD
    hook 을 트리거하고 keyboard state 도 갱신한다. KakaoTalk 처럼 hook 으로
    Enter 를 검증하는 앱에는 SendInput 만 통한다 (Microsoft 공식 답:
    devblogs.microsoft.com/oldnewthing 2025-03-19 "You can't simulate
    keyboard input with PostMessage, revisited" / rayshoo/kolemak IME 의
    카톡 호환 패턴: SendInput 으로 Enter 재주입).

    SendInput 은 현재 foreground 윈도우의 focused control 로 들어가므로
    호출자가 _force_foreground + _force_focus(target) 를 미리 해 두어야 한다.
    """
    user32, _ = _load_win32()
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    inputs = (_INPUT * 2)(
        _ki(vk, scan, 0),
        _ki(vk, scan, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(2, inputs, ctypes.sizeof(_INPUT))
    if sent != 2:
        err = ctypes.get_last_error()
        raise KakaoWinError(
            f"SendInput VK={vk:#x} 실패 (sent={sent}/2, GetLastError={err})."
        )


def _force_focus(target_hwnd: int) -> bool:
    """cross-thread SetFocus 를 AttachThreadInput 으로 우회.

    SetFocus 는 호출 스레드와 같은 입력 큐의 윈도우에만 통한다. 카톡 채팅창
    의 컨트롤들은 다른 프로세스 / 스레드라 AttachThreadInput 으로 입력 큐를
    묶은 뒤 SetFocus 해야 포커스가 실제로 이동한다.

    반환: GetFocus() 가 target_hwnd 와 같아졌는지 검증. False 면 cross-thread
    포커스 이동 실패 (caller 가 진단 / fallback 결정).
    """
    user32, kernel32 = _load_win32()
    cur_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(target_hwnd, None)
    if target_tid == 0:
        return False
    attached = False
    try:
        if target_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, target_tid, True))
        user32.SetFocus(target_hwnd)
        # GetFocus 는 호출 스레드의 입력 큐 기준. AttachThreadInput 으로
        # 큐가 합쳐진 동안만 target 의 focus 를 볼 수 있다.
        return user32.GetFocus() == target_hwnd
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, target_tid, False)


def _wait_visible_idx_change(
    child_hwnd: int,
    prev_idx: Optional[int],
    timeout_s: float = TAB_SWITCH_VERIFY_TIMEOUT_S,
    interval_s: float = TAB_SWITCH_POLL_INTERVAL_S,
) -> tuple[Optional[int], list[tuple[int, bool]]]:
    """Ctrl+Tab 보낸 뒤 visible idx 가 prev_idx 와 달라질 때까지 짧게 폴링."""
    deadline = time.monotonic() + timeout_s
    panels = _enum_eva_panels(child_hwnd)
    idx = _current_visible_panel_index(panels)
    while time.monotonic() < deadline:
        if idx is not None and idx != prev_idx:
            return idx, panels
        time.sleep(interval_s)
        panels = _enum_eva_panels(child_hwnd)
        idx = _current_visible_panel_index(panels)
    return idx, panels


def step2_focus_tab(hwnd: int, choice: str) -> None:
    """카카오톡 메인창의 탭을 choice(1=친구/2=채팅/3=더보기)로 전환.

    Mac 의 ⌘+1/⌘+2 와 의미상 동등하게 만들기 위해 EVA_Window visible 인덱스
    감지 + Ctrl+Tab 반복 패턴을 쓴다.
    """
    if choice not in TAB_CHOICES:
        raise KakaoWinError(
            f"잘못된 탭 선택: {choice!r} "
            f"({'/'.join(TAB_CHOICES)} 중 하나여야 함: 1=친구, 2=채팅, 3=더보기)"
        )

    # Step 1 ~ Step 2 사이 사용자가 다른 창을 클릭했을 수 있으니 한 번 더.
    _force_foreground(hwnd)
    if not wait_for_foreground(hwnd):
        raise KakaoWinError(
            f"카카오톡이 {FOREGROUND_TIMEOUT_S}s 안에 foreground 가 되지 "
            f"않았습니다. (step 2 직전 재확인 실패)"
        )

    child = _find_kakao_child_window(hwnd)
    if child is None:
        # 클래스명이 바뀐 빌드일 수 있으니 메인창의 직속 자식 클래스 목록 덤프.
        direct = _enum_direct_children(hwnd)
        print(
            f"[Step 2] 메인창(hwnd=0x{hwnd:08X}) 의 직속 자식 클래스 목록 "
            f"({KAKAO_CHILD_CLASS} 후보 없음):",
            file=sys.stderr,
        )
        for h in direct:
            print(
                f"  - hwnd=0x{h:08X} class={_get_class_name(h)!r}",
                file=sys.stderr,
            )
        raise KakaoWinError(
            f"{KAKAO_CHILD_CLASS} 자식 윈도우를 찾지 못했습니다. "
            "카카오톡 빌드에서 컨테이너 클래스명이 바뀌었을 수 있습니다."
        )

    panels = _enum_eva_panels(child)
    if not panels:
        # EVA_ChildWindow 의 직속 자식 클래스 목록 덤프.
        print(
            f"[Step 2] {KAKAO_CHILD_CLASS}(hwnd=0x{child:08X}) 의 직속 자식 "
            f"클래스 목록 ({KAKAO_PANEL_CLASS} 후보 없음):",
            file=sys.stderr,
        )
        for h in _enum_direct_children(child):
            print(
                f"  - hwnd=0x{h:08X} class={_get_class_name(h)!r}",
                file=sys.stderr,
            )
        raise KakaoWinError(
            f"{KAKAO_PANEL_CLASS} 탭 패널을 찾지 못했습니다. "
            "카카오톡 빌드 변경 또는 메인창이 예상과 다른 상태일 수 있습니다."
        )

    target_idx = int(choice) - 1
    if target_idx >= len(panels):
        _dump_panels_to_stderr(
            panels,
            f"[Step 2] 패널 목록 (target_idx={target_idx} 가 패널 수 "
            f"{len(panels)} 보다 큼):",
        )
        raise KakaoWinError(
            f"탭 {choice} (={TAB_LABELS[choice]}) 를 찾을 수 없습니다. "
            f"현재 카카오톡에는 {len(panels)} 개의 탭 패널만 잡힙니다."
        )

    current = _current_visible_panel_index(panels)
    if current == target_idx:
        print(
            f"[Step 2] {TAB_LABELS[choice]} 탭으로 포커스했습니다. "
            f"(이미 활성 탭, Ctrl+Tab × 0)"
        )
        return

    presses = 0
    last_idx = current
    for _ in range(TAB_SWITCH_MAX_PRESSES):
        _send_ctrl_tab()
        presses += 1
        time.sleep(TAB_SWITCH_AFTER_PRESS_S)
        new_idx, panels = _wait_visible_idx_change(child, last_idx)
        last_idx = new_idx
        if new_idx == target_idx:
            print(
                f"[Step 2] {TAB_LABELS[choice]} 탭으로 포커스했습니다. "
                f"(Ctrl+Tab × {presses})"
            )
            return

    _dump_panels_to_stderr(
        panels,
        f"[Step 2] Ctrl+Tab × {presses} 후에도 목표 탭(idx={target_idx}) "
        f"에 도달 못 함 / 마지막 visible idx={last_idx} / 패널 목록:",
    )
    raise KakaoWinError(
        f"탭 {choice} (={TAB_LABELS[choice]}) 로 전환 실패. "
        f"{TAB_SWITCH_MAX_PRESSES} 회 Ctrl+Tab 안에 도달하지 못했습니다. "
        "Step 2 동안 다른 키 입력 / 창 전환을 하지 마세요."
    )


# ---------------------------------------------------------------------------
# Step 3 — 현재 탭 상단 검색창에 텍스트 입력
# ---------------------------------------------------------------------------
#
# 현재 활성 탭(EVA_Window 패널)의 직속 자식인 표준 Win32 Edit 컨트롤을
# 직접 잡고, SendMessageW(WM_SETTEXT) 로 한글 그대로 set 한다. mac 의 pbcopy
# + ⌘V 우회는 IME 영향 회피용인데, Win32 Edit 의 W 메시지는 IME 와 무관해
# 클립보드 조작이 필요 없다 (Spy++ 분석: ssam2s.tistory.com/9, slaner.tistory.com/150).
#
# 주의:
#  - 비활성 탭의 EVA_Window 패널 안에도 같은 Edit 이 살아 있다. 반드시
#    Step 2 가 보장한 visible 패널 안의 Edit 만 쓴다 (안 그러면 안 보이는
#    탭에 입력이 들어감).
#  - WM_SETTEXT 의 lParam 은 LPCWSTR 포인터. ctypes 에서 c_wchar_p(text) 로
#    감싸 전달. argtypes 가 LPARAM (정수형) 이라도 c_wchar_p 는 자동으로
#    포인터 정수값으로 캐스트되며, 객체가 호출 동안 GC 되지 않게 변수에
#    잡아둔다.
#  - WM_SETTEXT 의 반환값은 1=성공 / 0=실패. 0 이면 GetLastError 와 함께
#    UIPI(관리자 권한 카톡 vs 일반 권한 스크립트) 가능성을 진단에 포함.
#  - Enter 미입력 — 결과 하이라이트 / Return 은 Step 5 의 책임.

def _find_search_edit(panel_hwnd: int) -> Optional[int]:
    """visible EVA_Window 패널의 직속 자식 중 클래스명이 'Edit' 인 첫 번째.

    EnumChildWindows 가 손자까지 재귀하므로 _enum_direct_children 으로
    GetParent == panel 인 것만 골라 검사한다.
    """
    for h in _enum_direct_children(panel_hwnd):
        if _get_class_name(h) == KAKAO_EDIT_CLASS:
            return h
    return None


def step3_set_search_text(hwnd: int, choice: str, query: str) -> None:
    """현재 탭(choice) 의 검색창에 query 를 입력. Enter 는 안 보낸다."""
    if choice not in TAB_CHOICES:
        raise KakaoWinError(
            f"잘못된 탭 선택: {choice!r} "
            f"({'/'.join(TAB_CHOICES)} 중 하나여야 함)"
        )
    if not query:
        raise KakaoWinError("검색어가 비어 있습니다.")

    # Step 2 ~ Step 3 사이 사용자가 다른 창을 클릭했을 수 있으니 한 번 더.
    _force_foreground(hwnd)
    if not wait_for_foreground(hwnd):
        raise KakaoWinError(
            f"카카오톡이 {FOREGROUND_TIMEOUT_S}s 안에 foreground 가 되지 "
            f"않았습니다. (step 3 직전 재확인 실패)"
        )

    child = _find_kakao_child_window(hwnd)
    if child is None:
        raise KakaoWinError(
            f"{KAKAO_CHILD_CLASS} 자식 윈도우를 찾지 못했습니다. "
            "(step 2 직후인데 사라졌다면 카카오톡이 닫혔거나 다른 창으로 "
            "교체됐을 수 있음)"
        )

    panels = _enum_eva_panels(child)
    target_idx = int(choice) - 1
    if target_idx >= len(panels):
        _dump_panels_to_stderr(
            panels,
            f"[Step 3] 패널 목록 (target_idx={target_idx} 가 패널 수 "
            f"{len(panels)} 보다 큼):",
        )
        raise KakaoWinError(
            f"탭 {choice} (={TAB_LABELS[choice]}) 의 패널이 없습니다."
        )

    current = _current_visible_panel_index(panels)
    if current != target_idx:
        _dump_panels_to_stderr(
            panels,
            f"[Step 3] 목표 탭(idx={target_idx}) 가 visible 이 아님 "
            f"(현재 visible idx={current}):",
        )
        raise KakaoWinError(
            f"Step 3 진입 시점에 {TAB_LABELS[choice]} 탭이 활성 상태가 "
            "아닙니다. (Step 2 직후에 다른 창/탭이 끼어든 것으로 보임)"
        )

    panel_hwnd = panels[target_idx][0]
    edit = _find_search_edit(panel_hwnd)
    if edit is None:
        # 빌드에 따라 검색창 클래스명이 바뀔 수 있으니 패널의 직속 자식
        # 클래스 목록을 stderr 에 덤프 (Step 1/2 의 진단 패턴).
        print(
            f"[Step 3] {KAKAO_PANEL_CLASS}(hwnd=0x{panel_hwnd:08X}) 의 직속 "
            f"자식 클래스 목록 ({KAKAO_EDIT_CLASS} 후보 없음):",
            file=sys.stderr,
        )
        for h in _enum_direct_children(panel_hwnd):
            print(
                f"  - hwnd=0x{h:08X} class={_get_class_name(h)!r}",
                file=sys.stderr,
            )
        raise KakaoWinError(
            f"{TAB_LABELS[choice]} 탭에서 검색창({KAKAO_EDIT_CLASS}) 컨트롤을 "
            "찾지 못했습니다. 카카오톡 빌드 변경으로 클래스명이 바뀌었을 "
            "수 있습니다."
        )

    user32, _ = _load_win32()
    # WM_SETTEXT 의 lParam 은 LPCWSTR 포인터. argtypes 가 LPARAM (정수형) 이라
    # ctypes.cast 로 정수 변환이 안 되므로 unicode 버퍼의 주소를 ctypes.addressof
    # 로 얻어 정수로 넘긴다. buf 는 호출 동안 변수에 잡아둬 GC 되지 않게 한다.
    text_buf = ctypes.create_unicode_buffer(query)
    ctypes.set_last_error(0)
    ret = user32.SendMessageW(
        edit, WM_SETTEXT, 0, ctypes.addressof(text_buf),
    )
    if ret != 1:
        err = ctypes.get_last_error()
        raise KakaoWinError(
            f"WM_SETTEXT 가 실패했습니다 (return={ret}, GetLastError={err}). "
            "카카오톡이 관리자 권한으로 실행 중이라면 스크립트도 같은 권한"
            "으로 실행해야 합니다 (Windows UIPI)."
        )

    print(f"[Step 3] 검색창에 입력 완료: {query!r}")


# ---------------------------------------------------------------------------
# Step 4/5/6 — 검색 결과 열기 + 타이틀 검증 (통합)
# ---------------------------------------------------------------------------
#
# 검색 결과 리스트 자체의 텍스트는 카톡의 EVA 커스텀 컨트롤이라 표준 Win32
# 메시지로 직접 읽어내기 까다롭다. 대신 카톡 PC 의 검증된 동작 — "검색 Edit
# 에 Enter 를 보내면 현재 하이라이트된(=첫) 결과가 새 채팅창 윈도우로 열린다"
# (ssam2s.tistory.com/9, airfox1.tistory.com/5) — 을 활용해, 결과를 한 칸씩
# 열어 본 뒤 "열린 채팅창의 top-level 윈도우 타이틀" 로 매칭을 검증한다.
#
# 한 시도 = (1) Enter → (2) 새로 뜬 윈도우 타이틀 확인 → (3) 매치면 종료,
# 불일치면 ESC (카톡 공식 "채팅방 닫기" 단축키) 로 즉시 닫고 ↓ 로 하이라이트
# 한 칸 이동. 사용자가 알아채기 전에 빠르게 빠져나오기 위해 폴링 타임아웃은
# 짧게 (1.5 s / 0.5 s) 잡았다.
#
# 무한 시도 방지: ↓ 가 리스트 끝에 도달하면 같은 방이 재오픈되므로, 같은
# title 이 연속 SAME_TITLE_BOTTOM_RUN(=3) 회 나오면 "리스트 끝" 으로 보고 멈춤.
# 최대 OPEN_MAX_ATTEMPTS(=10) 회 안에도 못 찾으면 실패.
#
# 키 입력은 PostMessage 로 검색 Edit / 채팅창 hwnd 에 직접 전송. Step 2 의
# Ctrl+Tab PostMessage 금지 노트는 modifier+key 의 시스템 키보드 상태 갱신
# 이슈인데, 여기서 쓰는 VK_RETURN/VK_DOWN/VK_ESCAPE 는 modifier 가 없어
# PostMessage 만으로 충분하다 (ssam2s/airfox1 의 검증된 패턴).

def _post_key(hwnd: int, vk: int) -> None:
    """PostMessage 로 WM_KEYDOWN + WM_KEYUP 한 쌍을 보낸다.

    lParam=0 으로도 카톡이 받아준다 (ssam2s/airfox1 의 검증된 패턴). 비활성
    hwnd 에도 메시지가 큐잉되므로 채팅창이 포커스 빼앗아가도 검색 Edit 에
    그대로 보낼 수 있다.
    """
    user32, _ = _load_win32()
    ok_down = user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    ok_up = user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)
    if not ok_down or not ok_up:
        err = ctypes.get_last_error()
        raise KakaoWinError(
            f"PostMessage 실패 (hwnd=0x{hwnd:08X}, vk=0x{vk:02X}, "
            f"down={bool(ok_down)} up={bool(ok_up)}, GetLastError={err})."
        )


def _find_search_list_ctrl(panel_hwnd: int) -> Optional[int]:
    """visible 검색 결과 리스트 컨트롤 hwnd 를 찾는다.

    각 EVA_Window 패널 안에는 같은 클래스 (EVA_VH_ListControl_Dblclk) 의
    리스트가 둘 있다 — 평소 채팅/친구 목록 (ChatRoomListCtrl_*) 과 검색
    결과 목록 (SearchListCtrl_*). 검색 중에는 SearchListCtrl 가 visible 로
    토글된다. title 접두사로 명시 구분하면 더 정확하지만, 단순히 "visible
    한 EVA_VH_ListControl_Dblclk" 만 잡아도 검색 중에는 SearchListCtrl 하나
    뿐이라 충분하다. 안전을 위해 title 접두사 우선, 없으면 visible 만으로 fallback.
    """
    user32, _ = _load_win32()
    candidates: list[int] = []
    for h in _enum_direct_children(panel_hwnd):
        if _get_class_name(h) != KAKAO_LIST_CTRL_CLASS:
            continue
        if not user32.IsWindowVisible(h):
            continue
        candidates.append(h)

    # 우선순위: title 이 SearchListCtrl_ 로 시작하는 것.
    for h in candidates:
        length = user32.GetWindowTextLengthW(h)
        if length <= 0:
            continue
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(h, buf, length + 1)
        if buf.value.startswith(KAKAO_SEARCH_LIST_TITLE_PREFIX):
            return h

    # fallback: visible 한 list ctrl 이 한 개뿐이면 그걸 쓴다.
    if len(candidates) == 1:
        return candidates[0]
    return None


def _find_matching_kakao_window(
    query: str,
) -> Optional[tuple[int, str, bool]]:
    """현재 카카오톡 top-level 윈도우 중 title 이 query 와 매치하는 첫 hwnd.

    반환: (hwnd, title, is_exact). 매치 없으면 None.

    우선순위:
      - title == query           → is_exact=True (강한 확정)
      - title 이 query 를 포함     → is_exact=False (CONTAINS, 약한 확정)

    mac.py 의 Step 6 동작과 같은 방식 — "어떤 윈도우든 query 와 일치하는
    title 이 있으면 열려있는 것" 으로 본다.
    """
    wins = _enum_kakao_windows()
    for h, title, _vis, _ico in wins:
        if title == query:
            return h, title, True
    for h, title, _vis, _ico in wins:
        if title and query != title and query in title:
            return h, title, False
    return None


def _wait_for_match_or_new_window(
    query: str,
    baseline: set[int],
    timeout_s: float = OPEN_VERIFY_TIMEOUT_S,
    interval_s: float = OPEN_VERIFY_POLL_INTERVAL_S,
) -> tuple[
    Optional[tuple[int, str, bool]],
    Optional[tuple[int, str]],
]:
    """Enter 후 (match, wrong) 둘 중 어느 게 먼저 잡히는지 폴링.

    반환: (match, wrong).
      - match = (hwnd, title, is_exact) — query 매치 윈도우 발견시. 우선.
      - wrong = (hwnd, title)          — match 가 없지만 baseline 에 없던
                                         새 title 있는 윈도우가 떴을 때
                                         (= 잘못된 결과가 열렸음).
      - 둘 다 None — 시간 안에 아무 변화 없음 (인라인 모드 / 빈 결과 가능성).

    이 두 가지를 한 폴링에서 같이 보는 이유: 잘못된 결과가 뜨더라도 그 자체가
    "Enter 가 무언가를 열었다" 는 신호라 다음 시도로 넘어갈 수 있다. 매치가
    뜨면 그게 항상 우선.
    """
    deadline = time.monotonic() + timeout_s
    wrong: Optional[tuple[int, str]] = None
    while time.monotonic() < deadline:
        m = _find_matching_kakao_window(query)
        if m is not None:
            return m, None
        # match 가 없어도 새 title 있는 윈도우가 있으면 그게 "잘못 열린 방".
        for h, title, _vis, _ico in _enum_kakao_windows():
            if h not in baseline and title:
                wrong = (h, title)
                # title 비교 한 번 더: 혹시 동시간대에 매치가 됐다면 위 _find
                # 가 잡았어야 하니, 여기 도달했다는 건 매치 아님.
                break
        if wrong is not None:
            return None, wrong
        time.sleep(interval_s)
    return None, None


def _wait_window_closed(
    hwnd: int,
    timeout_s: float = CLOSE_VERIFY_TIMEOUT_S,
    interval_s: float = OPEN_VERIFY_POLL_INTERVAL_S,
) -> bool:
    """ESC 보낸 뒤 해당 hwnd 가 KakaoTalk top-level 목록에서 사라지는지 폴링.

    카톡 빌드에 따라 hwnd 가 destroy 되지 않고 hidden 으로만 바뀌는 경우도
    있어서, "목록에서 사라짐" 또는 "visible=False" 둘 다 닫힘으로 본다.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for h, _t, vis, _i in _enum_kakao_windows():
            if h == hwnd:
                if not vis:
                    return True
                break
        else:
            return True
        time.sleep(interval_s)
    return False


def step4_5_6_open_and_verify(hwnd: int, choice: str, query: str) -> int:
    """검색 결과를 위에서부터 ↓/Enter 로 하나씩 열어 타이틀로 매칭 검증.

    성공시 매치된 채팅창 hwnd 반환. 실패시 KakaoWinError.

    매칭 우선순위:
      - title == query           → EXACT 매치 (강한 확정)
      - query in title           → CONTAINS 매치 (타이틀 장식 가능성, 약한 확정)
      - 그 외                    → 불일치, ESC 로 닫고 ↓ 로 다음 시도
    """
    if choice not in TAB_CHOICES:
        raise KakaoWinError(
            f"잘못된 탭 선택: {choice!r} ({'/'.join(TAB_CHOICES)} 중 하나여야 함)"
        )
    if not query:
        raise KakaoWinError("검색어가 비어 있습니다.")

    # Step 3 직후라도 사용자가 다른 창을 클릭했을 수 있으니 한 번 더 확인.
    _force_foreground(hwnd)
    if not wait_for_foreground(hwnd):
        raise KakaoWinError(
            f"카카오톡이 {FOREGROUND_TIMEOUT_S}s 안에 foreground 가 되지 "
            f"않았습니다. (step 4/5/6 직전 재확인 실패)"
        )

    child = _find_kakao_child_window(hwnd)
    if child is None:
        raise KakaoWinError(
            f"{KAKAO_CHILD_CLASS} 자식 윈도우를 찾지 못했습니다."
        )
    panels = _enum_eva_panels(child)
    target_idx = int(choice) - 1
    if target_idx >= len(panels):
        raise KakaoWinError(
            f"탭 {choice} (={TAB_LABELS[choice]}) 의 패널이 없습니다."
        )
    panel_hwnd = panels[target_idx][0]
    edit = _find_search_edit(panel_hwnd)
    if edit is None:
        raise KakaoWinError(
            f"{TAB_LABELS[choice]} 탭에서 검색창({KAKAO_EDIT_CLASS}) 컨트롤을 "
            "찾지 못했습니다. (step 3 직후인데 사라졌다면 빌드 변경 가능성)"
        )
    # 검색 결과 리스트 컨트롤은 ↓ navigation 의 타겟. Edit 에 PostMessage
    # 하면 single-line Edit 이 ↓ 를 그냥 먹어 하이라이트가 안 움직이지만,
    # SearchListCtrl 자신에 보내면 리스트 컨트롤이 직접 처리해 다음 row 로
    # 하이라이트를 옮긴다. 처음에는 못 잡혀 있을 수 있고 (검색 결과 채워지기
    # 전), Phase 0 직후의 initial delay 가 끝난 뒤 다시 잡는다.
    nav_target = _find_search_list_ctrl(panel_hwnd)

    # Phase 0 — 이미 query 와 일치하는 채팅창이 열려 있으면 즉시 성공.
    # (이전 호출에서 같은 사람을 열어 둔 상태 / 사용자가 직접 열어 둔 상태 등.)
    pre_existing = _find_matching_kakao_window(query)
    if pre_existing is not None:
        h, title, is_exact = pre_existing
        kind = "EXACT" if is_exact else "CONTAINS"
        print(
            f"[Step 4/5/6] 이미 열려 있는 채팅창 발견 -> title={title!r} "
            f"({kind}, hwnd=0x{h:08X}). Enter loop 생략."
        )
        return h

    # Enter 직후 결과 리스트가 갱신될 시간을 한 번 준다 (Step 3 의 WM_SETTEXT
    # 가 EN_CHANGE 통지 → 카톡이 비동기로 결과를 채우는 구조).
    time.sleep(OPEN_VERIFY_INITIAL_DELAY_S)

    # 검색 결과가 채워지면 SearchListCtrl 가 visible 로 토글되니, initial
    # delay 끝나고 다시 한 번 nav_target 을 잡아본다.
    if nav_target is None:
        nav_target = _find_search_list_ctrl(panel_hwnd)
    if nav_target is not None:
        print(
            f"[Step 4/5/6] ↓ navigation target = "
            f"SearchListCtrl hwnd=0x{nav_target:08X}",
            file=sys.stderr,
        )
    else:
        print(
            f"[Step 4/5/6] SearchListCtrl 못 잡음 → ↓ 를 Edit 에 fallback "
            "(친구탭처럼 ↓ navigation 불필요한 케이스일 수 있음).",
            file=sys.stderr,
        )

    baseline = {h for h, _t, _v, _i in _enum_kakao_windows()}
    last_titles: list[str] = []

    for attempt in range(1, OPEN_MAX_ATTEMPTS + 1):
        # 1) Enter — 현재 하이라이트된 결과를 새 채팅창으로 연다.
        _post_key(edit, VK_RETURN)

        # 2) match (성공) 또는 wrong (불일치 새 윈도우) 폴링.
        match, wrong = _wait_for_match_or_new_window(query, baseline)

        if match is not None:
            m_hwnd, m_title, m_exact = match
            kind = "EXACT" if m_exact else "CONTAINS"
            print(
                f"[Step 4/5/6] '{query}' {kind} 매치 -> title={m_title!r} "
                f"(시도 {attempt}/{OPEN_MAX_ATTEMPTS}, "
                f"{TAB_LABELS[choice]} 탭, hwnd=0x{m_hwnd:08X}). 채팅방 열림 확인."
            )
            return m_hwnd

        if wrong is None:
            # Enter 후 매치도, 새 윈도우도 안 떴음 → 인라인 모드 / 빈 결과 / 권한 문제.
            print(
                f"[Step 4/5/6] 시도 {attempt}/{OPEN_MAX_ATTEMPTS}: "
                f"Enter 후 {OPEN_VERIFY_TIMEOUT_S}s 안에 매치도 새 채팅창도 "
                "안 잡혔습니다. (검색 결과 비었거나 인라인 패널 모드일 가능성)",
                file=sys.stderr,
            )
            current = _enum_kakao_windows()
            print(
                f"  현재 카카오톡 top-level 윈도우 ({len(current)} 개):",
                file=sys.stderr,
            )
            for h, title, vis, ico in current:
                mark = " (baseline)" if h in baseline else " (NEW)"
                print(
                    f"    - hwnd=0x{h:08X} title={title!r} "
                    f"visible={vis} iconic={ico}{mark}",
                    file=sys.stderr,
                )
            raise KakaoWinError(
                f"검색 결과를 열지 못했습니다 (시도 {attempt}/{OPEN_MAX_ATTEMPTS}). "
                "검색 결과가 비었거나 카톡이 인라인 모드로 열고 있을 수 있습니다."
            )

        # 3) wrong — 잘못된 방이 열렸다. ESC 로 즉시 닫고 ↓ 로 다음.
        w_hwnd, w_title = wrong
        print(
            f"[Step 4/5/6] 시도 {attempt}/{OPEN_MAX_ATTEMPTS}: 불일치 "
            f"title={w_title!r} (hwnd=0x{w_hwnd:08X}) -> ESC 로 닫고 다음 시도.",
            file=sys.stderr,
        )
        _post_key(w_hwnd, VK_ESCAPE)
        if not _wait_window_closed(w_hwnd):
            print(
                f"[Step 4/5/6] 경고: ESC 후에도 hwnd=0x{w_hwnd:08X} 가 "
                f"{CLOSE_VERIFY_TIMEOUT_S}s 안에 안 닫혔습니다. "
                "(visible=False 로 숨겨졌을 수도 있음)",
                file=sys.stderr,
            )

        # 4) baseline 갱신 — 닫혔든 hidden 이든, 다음 시도의 "새 윈도우" 판정이
        #    이전 hwnd 와 섞이지 않도록 현재 시점 hwnd 집합을 다시 스냅샷.
        baseline = {h for h, _t, _v, _i in _enum_kakao_windows()}

        # 5) 리스트 끝 도달 감지 — 같은 title 이 SAME_TITLE_BOTTOM_RUN 회 연속.
        last_titles.append(w_title)
        if (
            len(last_titles) >= SAME_TITLE_BOTTOM_RUN
            and len(set(last_titles[-SAME_TITLE_BOTTOM_RUN:])) == 1
        ):
            print(
                f"[Step 4/5/6] 같은 title {w_title!r} 가 "
                f"{SAME_TITLE_BOTTOM_RUN} 회 연속 등장 -> ↓ 가 리스트 끝에 "
                "도달한 것으로 판단, 중단합니다.",
                file=sys.stderr,
            )
            raise KakaoWinError(
                f"'{query}' 와 일치하는 결과를 못 찾았습니다. "
                f"리스트 끝에 도달 (시도 {attempt}/{OPEN_MAX_ATTEMPTS}, "
                f"마지막 title={w_title!r})."
            )

        # 6) ↓ — 하이라이트 한 칸 아래. Edit 이 아니라 SearchListCtrl 에
        #    직접 보낸다 (Edit 은 single-line 이라 ↓ 를 그냥 먹어버림).
        _post_key(nav_target if nav_target is not None else edit, VK_DOWN)
        # 리스트 컨트롤이 ↓ 를 처리하고 하이라이트가 다음 row 로 옮겨갈 시간을 준다.
        time.sleep(OPEN_VERIFY_POLL_INTERVAL_S)

    print(
        f"[Step 4/5/6] {OPEN_MAX_ATTEMPTS} 회 시도 동안 본 title 목록:",
        file=sys.stderr,
    )
    for i, t in enumerate(last_titles, 1):
        print(f"    {i}. {t!r}", file=sys.stderr)
    raise KakaoWinError(
        f"'{query}' 와 일치하는 결과를 {OPEN_MAX_ATTEMPTS} 회 시도 안에 "
        f"못 찾았습니다 ({TAB_LABELS[choice]} 탭)."
    )


# ---------------------------------------------------------------------------
# Step 7 — 열린 채팅방에 메시지 붙여넣고 전송
# ---------------------------------------------------------------------------
#
# 카카오톡 PC 의 옛 표준 패턴 (airfox1.tistory.com/5, ssam2s.tistory.com/9,
# Xenia101/KakaoTalk-python, 오빠두 VBA 매크로) 은 모두 동일:
#   - SendMessage(edit, WM_SETTEXT, text)
#   - PostMessage(edit, WM_KEYDOWN, VK_RETURN, 0)
#   - PostMessage(edit, WM_KEYUP,   VK_RETURN, 0)
# 그런데 **최근 (2024 ~) 카카오톡 빌드에서는 이 패턴이 통하지 않는다.** 실측
# 진단으로 확인된 동작:
#   1) WM_SETTEXT 는 그대로 들어가서 RichEdit 의 텍스트는 정상 set 됨 (length
#      이 메시지 길이로 바뀜).
#   2) 그러나 그 직후 어떤 방식으로 Enter 를 보내도 (PostMessage WM_KEYDOWN/UP
#      / SendMessage WM_KEYDOWN/UP / SetKeyboardState+PostMessage 트릭 /
#      AttachThreadInput+SetFocus+SendInput) **전송 trigger 가 안 됨**.
#   3) **유일하게 동작한 패턴**: 클립보드에 메시지를 set 한 뒤 SendInput 으로
#      Ctrl+V (paste) + SendInput 으로 VK_RETURN. paste 후 RichEdit 의 텍스트
#      가 placeholder('메시지 입력') 로 토글되며 메시지가 실제 전송됨.
#
# 가설: 최근 카톡 RichEdit subclass 는 "이 텍스트는 사용자가 input pipeline 으
# 로 직접 친 거다" 라는 internal flag 가 있어야 Enter 를 send trigger 로
# 인식한다. WM_SETTEXT 로 직접 set 한 텍스트는 그 flag 가 없어 Enter 가 무시
# 된다. Ctrl+V (WM_PASTE) 로 들어간 텍스트는 flag 가 set 되어 Enter 가 send
# 로 동작한다. (Microsoft 공식 답
# devblogs.microsoft.com/oldnewthing 2025-03-19 "You can't simulate keyboard
# input with PostMessage, revisited" 의 일반 원리와도 일치 — input queue 를
# 거치지 않은 메시지는 hook / subclass 검증에서 걸린다.)
#
# 그래서 우리 구현 절차:
#   1) RichEdit 입력란 hwnd 찾기 (RichEdit50W / RichEdit20W / RichEdit*)
#   2) 채팅창 foreground 보장 + msg_edit 에 cross-thread SetFocus
#   3) 메시지 텍스트를 클립보드 (CF_UNICODETEXT) 에 set
#   4) SendInput 으로 Ctrl+V batch (VK_CONTROL down → VK_V down → up → up)
#   5) RichEdit 의 텍스트가 우리 메시지로 채워졌는지 폴링 검증 (paste 도달)
#   6) SendInput 으로 VK_RETURN (전송 trigger)
#   7) RichEdit 의 텍스트가 더 이상 우리 메시지가 아닌지 폴링 (= 전송됨)
#
# 검증 노트:
#   - "전송 성공" 의 정의 = 현재 RichEdit 텍스트 != 보낸 메시지 (보통 비어
#     있거나 placeholder '메시지 입력' 로 토글). length == 0 만 보는 검증은
#     placeholder 때문에 오작동.
#   - 한글 / 유니코드: 클립보드는 CF_UNICODETEXT (UTF-16) 로 set 해서 IME /
#     인코딩 변환 이슈 없이 그대로 paste.
#   - 클립보드는 사용자가 다른 데서 쓰던 내용을 덮어쓰므로 함수 종료시
#     원래 클립보드 내용을 복원 시도 (best-effort — CF_UNICODETEXT 만 복원).
#   - 줄바꿈 \n 이 들어 있어도 Ctrl+V paste 한 뒤 Enter 면 카톡이 multi-line
#     메시지로 전송 (Shift+Enter 가 줄바꿈, 그냥 Enter 가 전송).
#   - cross-thread SetFocus: AttachThreadInput 트릭 (_force_focus).
#   - Step 4/5/6 ~ Step 7 사이 사용자가 다른 창을 클릭했을 수 있어, 진입시
#     채팅창 hwnd 로 _force_foreground + wait_for_foreground 한 번 더.

def _enum_all_descendants(parent_hwnd: int) -> list[int]:
    """EnumChildWindows 의 default 동작 = 모든 후손 enumerate.

    Step 2/3 의 _enum_direct_children 은 손자까지 잡히지 않게 GetParent 로
    필터링했지만, Step 7 의 message edit fallback 은 채팅창이 RichEdit 을
    중간 컨테이너로 한 단계 감싸는 빌드도 커버해야 해서 손자/증손자까지
    전부 본다.
    """
    user32, _ = _load_win32()
    results: list[int] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        results.append(hwnd)
        return True

    cb = _EnumWindowsProc(_callback)  # 콜백 GC 방지
    user32.EnumChildWindows(parent_hwnd, cb, 0)
    return results


def _find_message_edit(chat_hwnd: int) -> Optional[tuple[int, str]]:
    """채팅창 안의 메시지 입력 RichEdit hwnd 와 그 클래스명을 반환.

    탐색 순서:
      1) 직속 자식 중 클래스 == 'RichEdit50W' / 'RichEdit20W' (canonical)
      2) 후손(grandchild 포함) 중 클래스가 'RichEdit' 로 시작 (build 변경 대비)
    """
    user32, _ = _load_win32()
    for cls in KAKAO_MSG_EDIT_CLASSES:
        h = user32.FindWindowExW(chat_hwnd, None, cls, None)
        if h:
            return h, cls
    for h in _enum_all_descendants(chat_hwnd):
        cls = _get_class_name(h)
        if cls.lower().startswith(KAKAO_MSG_EDIT_CLASS_PREFIX.lower()):
            return h, cls
    return None


def _dump_chat_descendants_to_stderr(chat_hwnd: int) -> None:
    """진단용: 채팅창의 모든 후손 (hwnd / class / title) 덤프."""
    print(
        f"[Step 7] chat hwnd=0x{chat_hwnd:08X} 후손 윈도우 목록 "
        f"(RichEdit* 후보 없음):",
        file=sys.stderr,
    )
    user32, _ = _load_win32()
    descendants = _enum_all_descendants(chat_hwnd)
    if not descendants:
        print("  (후손 윈도우 없음 — 잘못된 hwnd 일 수 있음)", file=sys.stderr)
        return
    for h in descendants:
        cls = _get_class_name(h)
        length = user32.GetWindowTextLengthW(h)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(h, buf, length + 1)
            title = buf.value
        print(
            f"  - hwnd=0x{h:08X} class={cls!r} title={title!r}",
            file=sys.stderr,
        )


def _get_edit_text(edit_hwnd: int) -> str:
    """RichEdit 의 현재 텍스트 내용 (WM_GETTEXT).

    Step 7 의 전송 검증 / paste 검증용. length 만 보지 않고 실제 내용을
    원본 메시지와 비교한다 (카톡은 빈 상태에서 placeholder '메시지 입력'
    을 표시하므로 length == 0 만으로는 빈 여부를 판정 못 함).
    """
    user32, _ = _load_win32()
    length = int(user32.SendMessageW(edit_hwnd, WM_GETTEXTLENGTH, 0, 0))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    # WM_GETTEXT: wParam = 버퍼 크기(문자 단위, NULL 포함), lParam = 버퍼 주소.
    user32.SendMessageW(
        edit_hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buf),
    )
    return buf.value


def _clipboard_set_unicode(text: str) -> None:
    """클립보드를 CF_UNICODETEXT 로 설정.

    SetClipboardData 는 hmem ownership 을 클립보드로 넘긴다 (즉 호출 후
    우리가 GlobalFree 하면 안 됨). GlobalAlloc(GMEM_MOVEABLE) + GlobalLock
    + memmove(wchar buffer) 패턴은 Win32 클립보드의 표준 사용법.

    중요 — surrogate pair (emoji 등 BMP 외 문자) 처리:
      Python `len(text)` 는 code point 개수라 이모지 (🎉 = 1 code point) 도
      1 로 세지만, UTF-16 / wchar_t 는 surrogate pair 로 2 unit 을 쓴다.
      그래서 `(len(text) + 1) * sizeof(c_wchar)` 로 alloc 하면 supplementary
      문자가 있을 때 버퍼 부족 → 마지막 surrogate 가 잘려 unpaired surrogate
      가 되고 카톡이 '?' 로 렌더한다. 반드시 **ctypes 가 계산한 wchar 버퍼
      의 실제 sizeof** 을 쓴다 (create_unicode_buffer 는 내부에서
      PyUnicode_AsWideChar 로 정확한 wchar_t 개수를 알아낸다).
    """
    user32, kernel32 = _load_win32()
    src_buf = ctypes.create_unicode_buffer(text)  # NULL terminator 포함 wchar 버퍼
    nbytes = ctypes.sizeof(src_buf)  # surrogate pair 까지 정확히 반영된 바이트 수
    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, nbytes)
    if not hmem:
        raise KakaoWinError(
            f"GlobalAlloc({nbytes}) 실패 (GetLastError={ctypes.get_last_error()})."
        )
    p = kernel32.GlobalLock(hmem)
    if not p:
        raise KakaoWinError(
            f"GlobalLock 실패 (GetLastError={ctypes.get_last_error()})."
        )
    try:
        ctypes.memmove(p, src_buf, nbytes)
    finally:
        kernel32.GlobalUnlock(hmem)

    # OpenClipboard 는 한 프로세스만 동시에 잡을 수 있어 짧게 재시도.
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.02)
    if not opened:
        raise KakaoWinError(
            "OpenClipboard 실패 — 다른 프로세스가 클립보드를 잡고 있습니다."
        )
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            raise KakaoWinError(
                f"SetClipboardData 실패 (GetLastError={ctypes.get_last_error()})."
            )
        # 성공시 ownership 이 클립보드로 넘어가 hmem 은 더 이상 우리 것이 아님.
    finally:
        user32.CloseClipboard()


def _clipboard_get_unicode() -> Optional[str]:
    """현재 클립보드의 CF_UNICODETEXT 내용 (없으면 None).

    Step 7 종료시 원래 내용을 복원하기 위해 사전에 저장용으로 호출.
    CF_UNICODETEXT 외 형식 (HTML / 이미지 / 파일 등) 은 본 함수로 보존
    불가 — best-effort.
    """
    user32, kernel32 = _load_win32()
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.02)
    if not opened:
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            # 클립보드 핸들에서 wide string 을 읽음. ctypes.wstring_at 은
            # null-terminated wide string 을 그대로 Python str 로 변환.
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def _send_ctrl_chord(vk: int, label: str) -> None:
    """SendInput 으로 Ctrl+<vk> batch 전송 (Ctrl+A / Ctrl+V 공용 헬퍼).

    순서: VK_CONTROL down → vk down → vk up → VK_CONTROL up. KEYBDINPUT 의
    `wScan` 까지 MapVirtualKeyW 로 채워 둠 (Step 2 와 같은 이유 — 일부 앱은
    wVk 만 보내면 무시).
    """
    user32, _ = _load_win32()
    ctrl_scan = user32.MapVirtualKeyW(VK_CONTROL, MAPVK_VK_TO_VSC)
    vk_scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    inputs = (_INPUT * 4)(
        _ki(VK_CONTROL, ctrl_scan, 0),
        _ki(vk, vk_scan, 0),
        _ki(vk, vk_scan, KEYEVENTF_KEYUP),
        _ki(VK_CONTROL, ctrl_scan, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(4, inputs, ctypes.sizeof(_INPUT))
    if sent != 4:
        err = ctypes.get_last_error()
        raise KakaoWinError(
            f"SendInput Ctrl+{label} 실패 (sent={sent}/4, GetLastError={err})."
        )


def _send_ctrl_v() -> None:
    """SendInput 으로 Ctrl+V batch 전송 (paste trigger)."""
    _send_ctrl_chord(VK_V, "V")


def _send_ctrl_a() -> None:
    """SendInput 으로 Ctrl+A batch 전송 (전체 선택).

    paste 전 호출하면 RichEdit 의 기존 텍스트가 모두 선택돼서, 이어지는
    Ctrl+V 가 선택 영역을 우리 메시지로 치환한다. 사용자가 손으로 친 잔여물
    이나 이전 자동화 실패로 남은 텍스트가 있어도 우리 메시지로 깔끔히
    덮어쓴다. 빈 입력란이면 Ctrl+A 는 no-op 라 부작용 없음.
    """
    _send_ctrl_chord(VK_A, "A")


def _normalize_newlines(s: str) -> str:
    """RichEdit 의 줄바꿈 표기를 정규화 (\\r\\n → \\n, 잔여 \\r → \\n).

    RichEdit 은 paste 받은 LF (\\n) 만의 텍스트를 내부에서 CRLF (\\r\\n) 로
    변환해 저장하고, WM_GETTEXT 로 읽을 때도 CRLF 로 돌려준다. 그래서 우리가
    보낸 message ('...\\n...') 와 paste 후 RichEdit 의 내용 ('...\\r\\n...')
    이 글자 비교에서 어긋난다. paste 검증 / 전송 검증 모두 줄바꿈을
    \\n 한 가지로 정규화 후 비교하면 이 차이를 흡수한다.
    """
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _wait_text_equals(
    edit_hwnd: int,
    expected: str,
    timeout_s: float = PASTE_VERIFY_TIMEOUT_S,
    interval_s: float = PASTE_VERIFY_POLL_INTERVAL_S,
) -> tuple[bool, str]:
    """RichEdit 텍스트가 expected 와 같아질 때까지 폴링 (paste 검증용).

    줄바꿈 표기 차이 (CRLF vs LF) 는 _normalize_newlines 로 흡수한다.
    """
    deadline = time.monotonic() + timeout_s
    exp_norm = _normalize_newlines(expected)
    last = _get_edit_text(edit_hwnd)
    while time.monotonic() < deadline:
        if _normalize_newlines(last) == exp_norm:
            return True, last
        time.sleep(interval_s)
        last = _get_edit_text(edit_hwnd)
    return _normalize_newlines(last) == exp_norm, last


def _wait_text_changed_from(
    edit_hwnd: int,
    original: str,
    timeout_s: float = MSG_VERIFY_TIMEOUT_S,
    interval_s: float = MSG_VERIFY_POLL_INTERVAL_S,
) -> tuple[bool, str]:
    """RichEdit 텍스트가 original 과 달라질 때까지 폴링 (전송 검증용).

    "전송 성공" 의 정의 = RichEdit 텍스트가 더 이상 우리가 보낸 그 메시지가
    아님 (보통 빈 문자열, 또는 placeholder '메시지 입력' 으로 토글).
    length == 0 만 보는 검증은 placeholder 때문에 오작동하므로 내용 비교.
    줄바꿈 표기 차이 (CRLF vs LF) 는 _normalize_newlines 로 흡수한다.
    """
    deadline = time.monotonic() + timeout_s
    orig_norm = _normalize_newlines(original)
    last = _get_edit_text(edit_hwnd)
    while time.monotonic() < deadline:
        if _normalize_newlines(last) != orig_norm:
            return True, last
        time.sleep(interval_s)
        last = _get_edit_text(edit_hwnd)
    return _normalize_newlines(last) != orig_norm, last


def _sanitize_message_for_richedit(message: str) -> str:
    """RichEdit paste 후 모양이 바뀌는 control char 를 사전 치환.

    - 탭 (\\t) → 4 spaces: RichEdit 은 paste 받은 \\t 를 tab stop 까지 가변
      길이 공백 (위치 기준 2~8 spaces) 으로 확장한다. 우리가 미리 4 spaces
      로 치환하면 paste 결과가 예측 가능해지고 검증이 정확해진다.
    - vertical tab (\\v) / form feed (\\f) → single space: 채팅 메시지에 거의
      쓰일 일이 없는 control char 들. RichEdit 이 paste 시 무시하거나
      줄바꿈으로 바꿔버려 검증이 어그러진다.
    - NULL (\\0) → 제거: 클립보드 wchar 문자열은 NULL 으로 종결되므로
      메시지 본문에 NULL 이 있으면 거기서 잘림. (사실상 일반 텍스트에
      NULL 이 있을 일은 없지만 안전 차원에서.)

    \\n 은 정상 line break 이므로 보존 (`_normalize_newlines` 가 CRLF↔LF
    차이를 흡수해 검증한다).
    """
    return (
        message
        .replace("\0", "")
        .replace("\v", " ")
        .replace("\f", " ")
        .replace("\t", "    ")
    )


def step7_send_message(chat_hwnd: int, message: str) -> None:
    """열린 채팅방(chat_hwnd) 의 입력란에 메시지를 paste 하고 Enter 로 전송.

    Step 4/5/6 가 반환한 채팅창 top-level hwnd 를 받는다. 성공 시 조용히
    리턴, 실패 시 KakaoWinError + stderr 진단.

    구현 절차 (실측으로 검증된 유일한 동작 패턴):
      1) RichEdit 입력란 hwnd 찾기
      2) 채팅창 foreground + msg_edit 에 cross-thread SetFocus
      3) 메시지 sanitize (탭 → 4 spaces 등) + 클립보드 (CF_UNICODETEXT) set
      4) SendInput 으로 Ctrl+A (전체 선택, 기존 잔여물 보호)
      5) SendInput 으로 Ctrl+V (paste) → RichEdit 이 메시지로 채워지길 폴링
      6) SendInput 으로 VK_RETURN (전송 trigger)
      7) RichEdit 의 텍스트가 sanitized 메시지에서 벗어났는지 폴링 (= 전송됨)
      8) 사전에 저장해 둔 원본 클립보드 내용 복원 (best-effort)
    """
    if not message:
        raise KakaoWinError("보낼 메시지가 비어 있습니다.")
    # 사용자가 보낸 메시지에 RichEdit 이 paste 시 변형하는 control char 가
    # 있으면 검증이 어그러진다. 미리 동일한 변형을 적용해서 paste 결과와
    # 비교 대상이 일치하게 한다. 변형 자체는 사용자가 손으로 paste 했을 때
    # 카톡에서 보이는 결과와 같다 (탭 → 공백).
    sanitized = _sanitize_message_for_richedit(message)
    if sanitized != message:
        print(
            f"[Step 7] 메시지 sanitize: control char 치환 (원본 {len(message)}자 "
            f"→ {len(sanitized)}자, 탭/수직탭/폼피드/NULL 정규화).",
            file=sys.stderr,
        )
    message = sanitized

    # Step 4/5/6 직후라도 사용자가 다른 창을 클릭했을 수 있으니 한 번 더 활성화.
    # 채팅창은 top-level 윈도우라 메인창과 같은 활성화 트릭이 그대로 통한다.
    _force_foreground(chat_hwnd)
    if not wait_for_foreground(chat_hwnd):
        print(
            f"[Step 7] 경고: 채팅창(hwnd=0x{chat_hwnd:08X}) 이 "
            f"{FOREGROUND_TIMEOUT_S}s 안에 foreground 가 되지 않았습니다. "
            "SendInput Ctrl+V / Enter 가 엉뚱한 창으로 갈 수 있지만 계속 "
            "진행합니다 (전송 검증 단계에서 결과 확정).",
            file=sys.stderr,
        )

    found = _find_message_edit(chat_hwnd)
    if found is None:
        _dump_chat_descendants_to_stderr(chat_hwnd)
        raise KakaoWinError(
            f"채팅방의 메시지 입력란을 찾지 못했습니다 "
            f"({' / '.join(KAKAO_MSG_EDIT_CLASSES)} / "
            f"{KAKAO_MSG_EDIT_CLASS_PREFIX}* 모두 미발견). "
            "카카오톡 빌드 변경으로 RichEdit 클래스명이 바뀌었을 수 있습니다."
        )
    msg_edit, edit_cls = found

    # cross-thread SetFocus. SendInput 은 foreground 윈도우의 focused 컨트롤로
    # 들어가므로 msg_edit 이 정확히 포커스를 잡고 있어야 한다. 못 잡혀도
    # 카톡 채팅창의 default focus 가 message edit 이라 대부분 자연스레 잡힘.
    focused = _force_focus(msg_edit)
    if not focused:
        print(
            f"[Step 7] 경고: msg_edit(hwnd=0x{msg_edit:08X}) 에 포커스 이동 "
            "검증 실패. 카톡 채팅창 default focus 가 msg_edit 일 거라 가정 "
            "하고 진행합니다.",
            file=sys.stderr,
        )

    # paste 전 RichEdit 의 현재 텍스트 진단 (실패 분석에 결정적). 사용자가
    # 손으로 친 잔여물 / 이전 자동화 실패의 찌꺼기 / 카톡의 임시 텍스트 등을
    # 즉시 식별할 수 있게 한다.
    pre_text = _get_edit_text(msg_edit)
    print(
        f"[Step 7] paste 전 msg_edit 상태: text={pre_text!r} "
        f"(focused={focused})",
        file=sys.stderr,
    )

    # 원본 클립보드 저장 — Step 7 종료시 복원 (best-effort, CF_UNICODETEXT 만).
    saved_clip = _clipboard_get_unicode()

    try:
        # 메시지를 클립보드에 set.
        _clipboard_set_unicode(message)

        # Ctrl+A — RichEdit 의 기존 텍스트를 모두 선택. 사용자가 손으로 친 잔여물
        # 이나 이전 실패한 자동화의 찌꺼기가 남아 있어도 다음 Ctrl+V 가 선택
        # 영역을 우리 메시지로 깔끔히 치환한다. 빈 입력란이면 no-op.
        _send_ctrl_a()
        # Ctrl+A 와 Ctrl+V 사이 짧은 sleep — RichEdit 이 selection 갱신을
        # 처리할 시간. 너무 짧으면 Ctrl+V 가 도착했을 때 아직 selection 이
        # 미반영이라 paste 가 의도와 다르게 동작할 수 있음.
        time.sleep(0.03)

        # Ctrl+V paste — RichEdit subclass 의 "user input pipeline" 으로 들어가
        # 메시지가 카톡의 "전송 가능 상태" 로 표시됨. (WM_SETTEXT 로 직접 set
        # 하면 이 flag 가 안 set 되어 Enter 가 무시됨 — 실측으로 확인.)
        _send_ctrl_v()

        # paste 가 도달해 RichEdit 의 텍스트가 우리 메시지로 채워졌는지 확인.
        pasted_ok, pasted_text = _wait_text_equals(msg_edit, message)
        if not pasted_ok:
            raise KakaoWinError(
                f"Ctrl+V 후 {PASTE_VERIFY_TIMEOUT_S}s 안에 RichEdit 내용이 "
                f"보낸 메시지와 같아지지 않았습니다 "
                f"(paste 전 텍스트={pre_text!r}, "
                f"현재 텍스트={pasted_text!r}, msg_edit=0x{msg_edit:08X}, "
                f"class={edit_cls!r}, focused={focused}). "
                "포커스가 다른 컨트롤로 빠졌거나 클립보드가 다른 형식으로 "
                "덮어쓰였을 수 있습니다 (다른 클립보드 매니저 / IME 충돌)."
            )

        # Enter — SendInput 으로 OS 입력 큐 주입. paste 한 텍스트가 user
        # input flag 가 set 된 상태라 카톡이 send trigger 로 인식.
        _send_vk_sendinput(VK_RETURN)

        # 전송 검증 — 텍스트가 우리 메시지에서 벗어났는지 확인 (보통 비거나
        # placeholder '메시지 입력' 으로 토글).
        sent_ok, after_text = _wait_text_changed_from(msg_edit, message)
        if not sent_ok:
            raise KakaoWinError(
                f"Enter 전송 후 {MSG_VERIFY_TIMEOUT_S}s 가 지나도 RichEdit "
                f"텍스트가 보낸 메시지 그대로입니다 "
                f"(텍스트={after_text!r}, msg_edit=0x{msg_edit:08X}, "
                f"class={edit_cls!r}, focused={focused}). "
                "카톡이 Enter 를 send trigger 로 인식하지 못했습니다 — "
                "포커스 / UIPI 권한 / 카카오톡 빌드 변경 가능성."
            )

        print(
            f"[Step 7] 메시지 전송 완료 (chat hwnd=0x{chat_hwnd:08X}, "
            f"msg_edit=0x{msg_edit:08X}, class={edit_cls!r}, "
            f"focused={focused}, paste={len(message)}자 → 전송 후 텍스트="
            f"{after_text!r})."
        )
    finally:
        # 원본 클립보드 내용 복원 (CF_UNICODETEXT 만 — HTML / 이미지 / 파일
        # 같은 다른 형식은 보존 불가, best-effort).
        if saved_clip is not None:
            try:
                _clipboard_set_unicode(saved_clip)
            except KakaoWinError as e:
                print(
                    f"[Step 7] 경고: 클립보드 복원 실패: {e}",
                    file=sys.stderr,
                )


# ---------------------------------------------------------------------------
# Step 8 — 열린 채팅방에 이미지/파일 전송
# ---------------------------------------------------------------------------

def _get_window_text(hwnd: int) -> str:
    """top-level / child 윈도우의 title 텍스트를 읽는다."""
    user32, _ = _load_win32()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _is_visible_window(hwnd: int) -> bool:
    user32, _ = _load_win32()
    return bool(user32.IsWindowVisible(hwnd))


def _resolve_existing_file_path(raw_path: str) -> Path:
    """CLI 에서 받은 파일 경로를 실제 Windows 파일로 해석한다.

    사용자가 mac/WSL 스타일 절대 경로(`/Users/.../a.png`)를 준 경우에도,
    같은 basename 이 현재 작업 폴더나 스크립트 폴더에 있으면 그 파일을 쓴다.
    """
    if not raw_path:
        raise KakaoWinError("전송할 파일 경로가 비어 있습니다.")

    raw = Path(raw_path).expanduser()
    script_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend((Path.cwd() / raw, script_dir / raw))
    # `/Users/.../name.ext` 처럼 이 Windows 세션에 없는 절대 경로를 받은 경우.
    candidates.extend((Path.cwd() / raw.name, script_dir / raw.name))

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
    raise KakaoWinError(
        f"전송할 파일을 찾지 못했습니다: {raw_path!r}. 확인한 후보: {searched}"
    )


def _wait_for_file_dialog(
    timeout_s: float = FILE_DIALOG_TIMEOUT_S,
    interval_s: float = FILE_SEND_POLL_INTERVAL_S,
) -> int:
    """Ctrl+T 뒤 카카오톡 소유의 표준 파일 열기 창을 기다린다."""
    user32, _ = _load_win32()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        fg = user32.GetForegroundWindow()
        if (
            fg
            and _get_window_text(fg) in FILE_DIALOG_TITLES
            and _get_class_name(fg) == "#32770"
        ):
            return fg
        for h, title, visible, _iconic in _enum_kakao_windows():
            if visible and title in FILE_DIALOG_TITLES and _get_class_name(h) == "#32770":
                return h
        time.sleep(interval_s)
    raise KakaoWinError(
        f"Ctrl+T 후 {timeout_s}s 안에 파일 열기 다이얼로그를 찾지 못했습니다."
    )


def _find_file_dialog_filename_edit(dialog_hwnd: int) -> int:
    """표준 열기 창의 '파일 이름' Edit 컨트롤을 찾는다."""
    edits = [
        h for h in _enum_all_descendants(dialog_hwnd)
        if _get_class_name(h) == "Edit" and _is_visible_window(h)
    ]
    if not edits:
        raise KakaoWinError(
            f"파일 열기 창(hwnd=0x{dialog_hwnd:08X})에서 파일명 Edit 컨트롤을 "
            "찾지 못했습니다."
        )
    # Windows common dialog 에서는 보통 visible Edit 이 1개다. 혹시 여럿이면
    # 마지막 visible Edit 이 파일 이름 ComboBox 안쪽 Edit 인 경우가 많다.
    return edits[-1]


def _find_file_dialog_open_button(dialog_hwnd: int) -> Optional[int]:
    for h in _enum_all_descendants(dialog_hwnd):
        if _get_class_name(h) != "Button" or not _is_visible_window(h):
            continue
        text = _get_window_text(h)
        if text.startswith("열기") or text.lower().startswith(("open", "&open")):
            return h
    return None


def _wait_for_file_send_preview(
    baseline: set[int],
    dialog_hwnd: int,
    timeout_s: float = FILE_SEND_PREVIEW_TIMEOUT_S,
    interval_s: float = FILE_SEND_POLL_INTERVAL_S,
) -> Optional[int]:
    """파일 선택 뒤 뜨는 카카오톡 '파일 전송' 확인창을 찾는다.

    현재 빌드에서는 title 이 빈 EVA_Window_Dblclk 으로 뜬다. 기존 광고/보조
    창도 title 이 비어 있을 수 있어, 파일 선택 직전 baseline 에 없던 새
    top-level 만 후보로 본다.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for h, _title, visible, _iconic in _enum_kakao_windows():
            if not visible or h in baseline or h == dialog_hwnd:
                continue
            return h
        time.sleep(interval_s)
    return None


def _kakao_top_level_visible(hwnd: int) -> bool:
    for h, _title, visible, _iconic in _enum_kakao_windows():
        if h == hwnd:
            return visible
    return False


def step8_send_file(chat_hwnd: int, file_path: str) -> None:
    """열린 채팅방에 이미지/파일 1개를 전송한다.

    검증된 흐름:
      1) 채팅창 + 입력 RichEdit 포커스
      2) Ctrl+T 로 카카오톡 파일 전송 다이얼로그 열기
      3) 표준 '열기' 창의 파일 이름 Edit 에 전체 경로를 paste
      4) Enter 로 선택
      5) 카카오톡 '파일 전송' 확인창에서 Enter 로 실제 전송
    """
    path = _resolve_existing_file_path(str(file_path))

    _force_foreground(chat_hwnd)
    if not wait_for_foreground(chat_hwnd):
        raise KakaoWinError(
            f"파일 전송 전 채팅창(hwnd=0x{chat_hwnd:08X}) 이 foreground 가 "
            "되지 않았습니다."
        )
    found = _find_message_edit(chat_hwnd)
    if found is not None:
        _force_focus(found[0])

    _send_ctrl_chord(VK_T, "T")
    dialog = _wait_for_file_dialog()
    _force_foreground(dialog)
    wait_for_foreground(dialog)

    edit = _find_file_dialog_filename_edit(dialog)
    open_button = _find_file_dialog_open_button(dialog)
    _force_focus(edit)
    saved_clip = _clipboard_get_unicode()
    try:
        # WM_SETTEXT 만으로는 common dialog 내부 ComboBox / 파일 리스트 선택
        # 이벤트가 갱신되지 않는 빌드가 있어, 실제 사용자 입력처럼 paste 한다.
        _clipboard_set_unicode(str(path))
        _send_ctrl_a()
        time.sleep(0.05)
        _send_ctrl_v()
        time.sleep(0.2)
    finally:
        if saved_clip is not None:
            try:
                _clipboard_set_unicode(saved_clip)
            except KakaoWinError as e:
                print(
                    f"[Step 8] 경고: 클립보드 복원 실패: {e}",
                    file=sys.stderr,
                )

    baseline = {h for h, _title, _visible, _iconic in _enum_kakao_windows()}
    _send_vk_sendinput(VK_RETURN)
    time.sleep(0.4)
    if _kakao_top_level_visible(dialog) and open_button is not None:
        # 일부 환경에서 Enter 가 파일명 Edit 안에서만 처리되면 열기 버튼을 직접 누른다.
        user32, _ = _load_win32()
        user32.SendMessageW(open_button, BM_CLICK, 0, 0)

    preview = _wait_for_file_send_preview(baseline, dialog)
    if _kakao_top_level_visible(dialog):
        raise KakaoWinError(
            f"파일 선택 후에도 열기 다이얼로그가 닫히지 않았습니다: {path}"
        )

    if preview is not None:
        _force_foreground(preview)
        wait_for_foreground(preview)
        _send_vk_sendinput(VK_RETURN)
        if not _wait_window_closed(preview, timeout_s=FILE_SEND_CLOSE_TIMEOUT_S):
            raise KakaoWinError(
                f"파일 전송 확인창(hwnd=0x{preview:08X}) 이 "
                f"{FILE_SEND_CLOSE_TIMEOUT_S}s 안에 닫히지 않았습니다: {path}"
            )
    else:
        print(
            f"[Step 8] 파일 선택 후 별도 확인창이 감지되지 않았습니다: {path.name}",
            file=sys.stderr,
        )

    print(f"[Step 8] 파일 전송 완료: {path} ({path.stat().st_size} bytes)")


def step8_send_files(chat_hwnd: int, file_paths: list[str]) -> None:
    """열린 채팅방에 파일 여러 개를 순서대로 전송한다."""
    for idx, raw_path in enumerate(file_paths, 1):
        print(f"[Step 8] 파일 {idx}/{len(file_paths)} 전송 시작: {raw_path}")
        step8_send_file(chat_hwnd, raw_path)


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def _prompt_tab() -> str:
    while True:
        raw = input(
            "어디로 포커스할까요? [1] 친구  [2] 채팅  [3] 더보기 : "
        ).strip()
        if raw in TAB_CHOICES:
            return raw
        print("1, 2, 3 중 하나만 입력해주세요.")


def _prompt_query() -> str:
    while True:
        raw = input("검색어를 입력하세요: ").strip()
        if raw:
            return raw
        print("빈 문자열은 안 됩니다.")


def _prompt_message() -> str:
    while True:
        # rstrip 만 (앞쪽 공백은 의도일 수 있음). 빈 문자열만 거부.
        raw = input("보낼 메시지를 입력하세요 (비우면 전송 생략): ").rstrip(
            "\r\n"
        )
        return raw  # 빈 문자열이면 step 7 생략 (main 에서 처리)


def _prompt_send_kind() -> str:
    while True:
        raw = input("무엇을 보낼까요? [1] 메시지  [2] 파일/이미지 : ").strip()
        if raw in ("1", "2"):
            return raw
        print("1 또는 2 중 하나만 입력해주세요.")


def _split_file_input(raw: str) -> list[str]:
    """파일 prompt 입력을 경로 목록으로 바꾼다.

    기본은 입력 전체를 파일 1개로 본다. 여러 파일을 한 번에 보내고 싶을 때만
    세미콜론(;) 또는 콤마(,)로 구분한다.
    """
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
        f"사용법: python {sys.argv[0]} [1|2|3] [\"검색어\"] [\"메시지\"] "
        "[--file 파일경로 ...]\n"
        "  1 = 친구, 2 = 채팅, 3 = 더보기\n"
        "  예) python kakao_win.py 2\n"
        "      python kakao_win.py 2 \"홍길동\"\n"
        "      python kakao_win.py 2 \"홍길동\" \"안녕하세요\"\n"
        "      python kakao_win.py 2 \"홍길동\" --file a.png --file Lunching.pdf\n"
        "  메시지를 빼면 Step 4/5/6 까지 (채팅방만 열고 끝).\n"
        "  인자 없이 실행하면 [1] 메시지 / [2] 파일·이미지를 선택합니다.\n"
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
    try:
        _ensure_windows()
    except KakaoWinError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1

    try:
        args, file_paths = _parse_cli_args(sys.argv[1:])
    except ValueError as e:
        print(f"[오류] {e}", file=sys.stderr)
        _print_usage()
        return 2

    tab: Optional[str] = None
    query: Optional[str] = None
    # message 는 3 종류 상태:
    #   - None         : 인자로 안 줬음 → 인터랙티브 prompt (빈 입력이면 생략)
    #   - ""           : 인자로 명시적으로 빈 문자열 → step 7 생략
    #   - 비어있지 않음 : 그 문자열을 전송
    message: Optional[str] = None
    message_arg_given = False

    if len(args) > 3:
        _print_usage()
        return 2
    if len(args) >= 1:
        if args[0] not in TAB_CHOICES:
            _print_usage()
            return 2
        tab = args[0]
    if len(args) >= 2:
        if not args[1]:
            _print_usage()
            return 2
        query = args[1]
    if len(args) >= 3:
        # 메시지는 빈 문자열도 허용 (step 7 생략 의도).
        message = args[2]
        message_arg_given = True

    # 모든 input() 은 step 시작 전에. 단계 중간에 input 받으면 터미널로
    # 포커스가 빠져 키 입력이 새는다 (mac.md 와 같은 노트).
    if tab is None:
        tab = _prompt_tab()
    if query is None:
        query = _prompt_query()
    if message is None and not message_arg_given:
        if file_paths:
            # 파일만 보내는 호출에서는 터미널 prompt 로 포커스를 빼앗지 않는다.
            message = ""
        else:
            send_kind = _prompt_send_kind()
            if send_kind == "1":
                message = _prompt_message()
            else:
                message = ""
                file_paths = _prompt_file_paths()

    try:
        hwnd = step1_activate_kakao()
        step2_focus_tab(hwnd, tab)
        step3_set_search_text(hwnd, tab, query)
        chat_hwnd = step4_5_6_open_and_verify(hwnd, tab, query)
        if message:
            step7_send_message(chat_hwnd, message)
        else:
            print("[Step 7] (생략) 빈 메시지라 전송하지 않습니다.")
        if file_paths:
            step8_send_files(chat_hwnd, file_paths)
    except KakaoWinError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
