"""给前端静态资源补上缓存策略。

打包成 exe 后前端产物是内置的，但 `index.html` 的文件名永远不变。浏览器
对没有 `Cache-Control` 的响应会按 `Last-Modified` 做启发式缓存，于是出现
"换了新版本、exe 也是新的，页面上看到的还是旧界面"这种问题。

规则按文件类型分两档：

- `/assets/` 下的文件名由 Vite 写入内容哈希（如 `index-CbkUX14t.js`），
  内容一变文件名就变，可以放心让浏览器长期缓存，省掉重复下载；
- 其余（`index.html`、favicon 等）必须每次回源校验，命中就用 304 省流量，
  内容变了立刻拿到新版本。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, MutableMapping

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Vite 产物统一放在 /assets/ 下，文件名带内容哈希。
IMMUTABLE_PREFIX = "/assets/"
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
REVALIDATE_CACHE_CONTROL = "no-cache"


class CacheControlledStatic:
    """`StaticFiles` 的薄包装：只做一件事——按路径写 `Cache-Control`。

    之所以不直接在 `StaticFiles` 上想办法，是因为它没有暴露"按路径设置响应
    头"的钩子；而换掉自己的 ASGI 包装层只有十几行，还不用改 FastAPI 的
    挂载方式。
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        value = (
            IMMUTABLE_CACHE_CONTROL
            if path.startswith(IMMUTABLE_PREFIX)
            else REVALIDATE_CACHE_CONTROL
        )

        async def send_with_cache_control(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = [
                    (name, header_value)
                    for name, header_value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", value.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_with_cache_control)
