"""单端口托管测试：后端直接提供前端构建产物（dist）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from devlog.server.app import DEFAULT_WEB_DIST, create_app, resolve_web_dist


INDEX_HTML = (
    "<!doctype html><html><head><title>DevLog</title></head>"
    "<body><div id=\"root\">DevLog</div></body></html>"
)


class ResolveWebDistTests(unittest.TestCase):
    """只认「目录里真的有 index.html」，空目录不算可用产物。"""

    def test_returns_none_when_directory_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_web_dist(Path(tmp) / "not-built"))

    def test_returns_none_when_index_html_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "assets").mkdir()
            self.assertIsNone(resolve_web_dist(tmp))

    def test_returns_directory_when_index_html_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text(INDEX_HTML, encoding="utf-8")
            self.assertEqual(resolve_web_dist(tmp), Path(tmp))

    def test_default_dist_points_at_web_frontend_build(self) -> None:
        self.assertEqual(DEFAULT_WEB_DIST.name, "dist")
        self.assertEqual(DEFAULT_WEB_DIST.parent.name, "web")
        self.assertEqual(DEFAULT_WEB_DIST.parent.parent.name, "devlog")


class SinglePortServingTests(unittest.TestCase):
    """有 dist 时一个端口同时提供页面和 API。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dist = self.root / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text(
            "console.log('devlog');\n", encoding="utf-8"
        )
        self.db_path = self.root / "web.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_root_serves_index_html(self) -> None:
        app = create_app(self.db_path, web_dir=self.dist)
        with TestClient(app) as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("DevLog", response.text)

    def test_static_asset_is_served(self) -> None:
        app = create_app(self.db_path, web_dir=self.dist)
        with TestClient(app) as client:
            response = client.get("/assets/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("devlog", response.text)

    def test_api_routes_are_not_shadowed_by_static_mount(self) -> None:
        app = create_app(self.db_path, web_dir=self.dist)
        with TestClient(app) as client:
            response = client.get("/api/projects")
            created = client.post(
                "/api/projects",
                json={"path": str(self.root / "repo")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        # 注册不存在的仓库应该报业务错误，而不是被静态挂载吞成 404 页面。
        self.assertEqual(created.status_code, 400)

    def test_app_state_records_resolved_web_dist(self) -> None:
        app = create_app(self.db_path, web_dir=self.dist)
        self.assertEqual(app.state.web_dist, str(self.dist))

    def test_without_build_only_api_is_available(self) -> None:
        app = create_app(self.db_path, web_dir=self.root / "not-built")
        with TestClient(app) as client:
            page = client.get("/")
            api = client.get("/api/projects")
        self.assertEqual(page.status_code, 404)
        self.assertEqual(api.status_code, 200)
        self.assertIsNone(app.state.web_dist)


if __name__ == "__main__":
    unittest.main()
