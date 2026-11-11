"""Reject requests whose declared body size is too large before the body is read.

Without this, the multipart parser would receive and spool the whole body before the upload endpoint
can check the file size. Chunked requests without a Content-Length are still limited by the
endpoint; in production the ingress also enforces a body limit.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ContentLengthLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._declared_size(scope) > self.max_bytes:
            response = JSONResponse(
                {"detail": f"Request body is larger than {self.max_bytes} bytes."},
                status_code=413,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _declared_size(scope: Scope) -> int:
        for name, value in scope["headers"]:
            if name == b"content-length" and value.isdigit():
                return int(value)
        return 0
