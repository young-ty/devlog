"""系统文件夹选择框接口测试：注入假 picker，绝不弹真实窗口。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from devlog.server import desktop
from devlog.server.app import create_app, is_loopback_request


ROOT = Path(__file__).resolve().parent.parent
LOCAL_CLIENT = ("127.0.0.1", 51234)
REMOTE_CLIENT = ("192.168.1.20", 51234)


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, client: _FakeClient | None) -> None:
        self.client = client


class LoopbackPredicateTests(unittest.TestCase):
    """本机特权必须能挡住局域网来的请求。"""

    def test_loopback_addresses_are_accepted(self) -> None:
        for host in ("127.0.0.1", "::1", "localhost", "127.0.0.5"):
            with self.subTest(host=host):
                request = _FakeRequest(_FakeClient(host))
                self.assertTrue(is_loopback_request(request))

    def test_remote_and_unknown_sources_are_rejected(self) -> None:
        for host in ("192.168.1.20", "10.0.0.5", "testclient", "fe80::1"):
            with self.subTest(host=host):
                request = _FakeRequest(_FakeClient(host))
                self.assertFalse(is_loopback_request(request))

    def test_missing_client_is_rejected(self) -> None:
        self.assertFalse(is_loopback_request(_FakeRequest(None)))


class DirectoryPickerEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "picker.db"
        self.plain_dir = self.root / "not-a-repo"
        self.plain_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def post(self, picker, client=LOCAL_CLIENT):
        app = create_app(self.db_path, directory_picker=picker)
        with TestClient(app, client=client) as test_client:
            return test_client.post("/api/system/pick-directory")

    def test_picked_git_repository_is_returned_with_flag(self) -> None:
        response = self.post(lambda: str(ROOT))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["path"], str(ROOT))
        self.assertTrue(body["is_git_repo"])
        self.assertFalse(body["cancelled"])

    def test_picked_folder_without_git_is_flagged(self) -> None:
        response = self.post(lambda: str(self.plain_dir))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["path"], str(self.plain_dir))
        self.assertFalse(body["is_git_repo"])

    def test_cancel_returns_cancelled_without_path(self) -> None:
        response = self.post(lambda: None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"cancelled": True, "path": None, "is_git_repo": False},
        )

    def test_remote_request_is_rejected_and_picker_not_called(self) -> None:
        calls: list[str] = []

        def picker() -> str:
            calls.append("called")
            return str(ROOT)

        response = self.post(picker, client=REMOTE_CLIENT)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(calls, [])

    def test_busy_picker_maps_to_409(self) -> None:
        def picker() -> str:
            raise desktop.DirectoryPickerBusy("已经有一个选择框打开了")

        response = self.post(picker)
        self.assertEqual(response.status_code, 409)
        self.assertIn("选择框", response.json()["detail"])

    def test_unavailable_picker_maps_to_503(self) -> None:
        def picker() -> str:
            raise desktop.DirectoryPickerError("没有桌面环境")

        response = self.post(picker)
        self.assertEqual(response.status_code, 503)
        self.assertIn("没有桌面环境", response.json()["detail"])

    def test_pick_directory_does_not_register_project(self) -> None:
        """选目录只返回路径，不注册项目 —— 注册是用户点按钮那一刻的事。"""

        app = create_app(self.db_path, directory_picker=lambda: str(ROOT))
        with TestClient(app, client=LOCAL_CLIENT) as test_client:
            test_client.post("/api/system/pick-directory")
            projects = test_client.get("/api/projects").json()
        self.assertEqual(projects, [])


class DesktopModuleTests(unittest.TestCase):
    def test_is_available_returns_bool(self) -> None:
        self.assertIsInstance(desktop.is_available(), bool)

    def test_concurrent_call_is_rejected_while_dialog_open(self) -> None:
        self.assertTrue(desktop._PICKER_LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(desktop.DirectoryPickerBusy):
                desktop.pick_directory()
        finally:
            desktop._PICKER_LOCK.release()

    def test_lock_is_released_after_dialog_closes(self) -> None:
        """弹窗结束后必须释放锁，否则之后再也弹不出来。"""

        original = desktop._ask_directory
        desktop._ask_directory = lambda title, initial_dir: None
        try:
            self.assertIsNone(desktop.pick_directory())
        finally:
            desktop._ask_directory = original
        self.assertTrue(desktop._PICKER_LOCK.acquire(blocking=False))
        desktop._PICKER_LOCK.release()


if __name__ == "__main__":
    unittest.main()
