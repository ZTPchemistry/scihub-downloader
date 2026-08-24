"""HTTP 会话与速率限制。

关键点：**两个 SSL 上下文**。
- Sci-Hub 镜像的证书常年是自签名/不匹配的，必须关掉校验（原脚本全局这么做）。
- 但 CrossRef 是正规服务，必须走默认校验，否则元数据可被中间人篡改。

二者绝不能混用。
"""

from __future__ import annotations

import ssl
import threading
import time
import urllib.error
import urllib.request

__all__ = ["HttpSession", "RateLimiter", "RequestError", "BROWSER_UA"]

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class RequestError(Exception):
    """统一的请求失败异常，携带可读原因。"""


def _make_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class HttpSession:
    """封装 urllib 的 GET 请求。

    ``strict=True`` 用校验上下文（CrossRef），否则用宽松上下文（Sci-Hub）。
    """

    def __init__(self, user_agent: str = BROWSER_UA, timeout: float = 60.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self._permissive = _make_context(verify=False)
        self._strict = _make_context(verify=True)

    def _request(self, url: str, strict: bool, timeout: float):
        ctx = self._strict if strict else self._permissive
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)

    def get(self, url: str, *, strict: bool = False, timeout: float | None = None) -> str:
        """返回解码后的文本。尽量尊重响应头里的字符集。"""
        t = self.timeout if timeout is None else timeout
        try:
            with self._request(url, strict, t) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            raise RequestError(f"HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise RequestError(str(e.reason)) from e
        except Exception as e:  # noqa: BLE001 —— 网络层统一归一化
            raise RequestError(str(e)) from e

    def open(
        self, url: str, *, strict: bool = False, timeout: float | None = None
    ):
        """返回流式响应对象，供下载器分块读取（不整体读入内存）。"""
        t = self.timeout if timeout is None else timeout
        try:
            return self._request(url, strict, t)
        except urllib.error.HTTPError as e:
            raise RequestError(f"HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise RequestError(str(e.reason)) from e
        except Exception as e:  # noqa: BLE001
            raise RequestError(str(e)) from e


class RateLimiter:
    """按 key 维度的最小请求间隔，避免对同一镜像连发被屏蔽。

    线程安全：Sci-Hub 下载引擎会从线程池里并发调用。
    """

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last.get(key, 0.0)
            delta = last + self.interval - now
            if delta > 0:
                time.sleep(delta)
            self._last[key] = time.monotonic()
