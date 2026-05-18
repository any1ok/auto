import importlib.util
import pathlib
import unittest
from unittest.mock import patch


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "autosend_automation.py"
spec = importlib.util.spec_from_file_location("autosend_automation", MODULE_PATH)
automation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(automation)


class FakeTools:
    def __init__(self):
        self.calls = []

    def key_down(self, key):
        self.calls.append(("key_down", key))

    def key_up(self, key):
        self.calls.append(("key_up", key))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def press(self, key):
        self.calls.append(("press", key))

    def paste_text(self, text):
        self.calls.append(("paste", text))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def sleep(self, seconds):
        self.calls.append(("sleep", seconds))


class DryRunTests(unittest.TestCase):
    @patch.object(automation, "activate_kakaotalk", lambda steps: steps.append("activated"))
    @patch.object(automation, "macos_accessibility_trusted", lambda: True)
    @patch.object(automation, "macos_front_window_title", lambda: "테스트방")
    @patch.object(automation, "macos_front_window_bounds", lambda: (10, 20, 400, 600))
    @patch.object(automation, "macos_post_key", lambda key, command=False: False)
    @patch.object(automation.platform, "system", lambda: "Darwin")
    @patch.object(
        automation,
        "macos_paste_message_and_maybe_send",
        lambda message, dry_run, tools, steps: steps.extend(
            ["used_current_focus_for_message_input", "pasted_message", "dry_run_requested_but_send_forced", "pressed_send"]
        ),
    )
    def test_dry_run_sends_after_user_request(self):
        tools = FakeTools()
        result = automation.run_kakao_send("테스트방", "안녕하세요", True, tools, search_delay=0)

        self.assertTrue(result.ok)
        self.assertTrue(result.dryRun)
        self.assertTrue(result.sent)
        self.assertIn("dry_run_requested_but_send_forced", result.steps)
        self.assertIn("pressed_send", result.steps)
        self.assertEqual([call for call in tools.calls if call == ("press", "enter")], [])

    @patch.object(automation, "activate_kakaotalk", lambda steps: steps.append("activated"))
    @patch.object(automation, "macos_accessibility_trusted", lambda: True)
    @patch.object(automation, "macos_front_window_title", lambda: "테스트방")
    @patch.object(automation, "macos_front_window_bounds", lambda: (10, 20, 400, 600))
    @patch.object(automation, "macos_post_key", lambda key, command=False: False)
    @patch.object(automation.platform, "system", lambda: "Darwin")
    @patch.object(
        automation,
        "macos_paste_message_and_maybe_send",
        lambda message, dry_run, tools, steps: steps.extend(["used_current_focus_for_message_input", "pasted_message", "pressed_send"]),
    )
    def test_real_send_presses_enter_twice(self):
        tools = FakeTools()
        result = automation.run_kakao_send("테스트방", "안녕하세요", False, tools, search_delay=0)

        self.assertTrue(result.ok)
        self.assertTrue(result.sent)
        self.assertIn("pressed_send", result.steps)
        self.assertEqual([call for call in tools.calls if call == ("press", "enter")], [])

    @patch.object(automation, "macos_front_window_bounds", lambda: (10, 20, 400, 600))
    @patch.object(automation, "find_macos_kakao_text_input", lambda steps: None)
    @patch.object(automation, "macos_click_send_button", lambda tools, steps, text_target: False)
    @patch.object(automation, "set_clipboard_text", lambda text: None)
    @patch.object(automation, "macos_post_key", lambda key, command=False: command and key == "v")
    def test_macos_paste_message_uses_cg_event_paste_when_no_ax_target(self):
        tools = FakeTools()
        steps = []

        automation.macos_paste_message_and_maybe_send("안녕하세요", False, tools, steps)

        self.assertIn(("click", 210, 576), tools.calls)
        self.assertNotIn(("paste", "안녕하세요"), tools.calls)
        self.assertIn("cg_event_command_v", steps)
        self.assertIn("pressed_send", steps)

    @patch.object(automation.platform, "system", lambda: "Darwin")
    @patch.object(automation, "macos_post_key", lambda key, command=False: False)
    def test_macos_command_key_uses_keydown_and_keyup(self):
        tools = FakeTools()

        automation.macos_press_command_key(tools, "v")

        self.assertEqual(
            tools.calls,
            [("key_down", "command"), ("sleep", 0.08), ("press", "v"), ("sleep", 0.08), ("key_up", "command")],
        )

    @patch.object(automation, "activate_kakaotalk", lambda steps: steps.append("activated"))
    @patch.object(automation, "macos_accessibility_trusted", lambda: True)
    @patch.object(automation, "macos_front_window_title", lambda: "다른방")
    @patch.object(automation, "macos_post_key", lambda key, command=False: False)
    @patch.object(automation.platform, "system", lambda: "Darwin")
    def test_fails_when_room_cannot_be_verified(self):
        tools = FakeTools()
        result = automation.run_kakao_send("테스트방", "안녕하세요", False, tools, search_delay=0)

        self.assertFalse(result.ok)
        self.assertIn("채팅방을 열지 못했습니다", result.error)

    def test_rejects_empty_message(self):
        result = automation.run_kakao_send("테스트방", " ", True, FakeTools(), search_delay=0)
        self.assertFalse(result.ok)
        self.assertIn("메시지", result.error)


if __name__ == "__main__":
    unittest.main()
