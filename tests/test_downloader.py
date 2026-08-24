"""下载引擎的离线测试：用假 session 验证整条流程，不发真实网络请求。"""

import threading
import unittest

from scihub_dl.downloader import BatchEngine, extract_pdf_url, resolve_pdf_url
from scihub_dl.mirrors import MirrorPool
from scihub_dl.models import Paper, STATUS_NETWORK_ERROR
from scihub_dl.net import RateLimiter, RequestError


class TestExtractPdfUrl(unittest.TestCase):
    def test_iframe_relative_resolves_against_base(self):
        # 相对 / 路径必须拼接到实际响应镜像，而不是硬编码 sci-hub.se。
        html = '<iframe src="/downloads/2021/foo.pdf#navpanes=0"></iframe>'
        self.assertEqual(
            extract_pdf_url(html, "https://sci-hub.vg"),
            "https://sci-hub.vg/downloads/2021/foo.pdf#navpanes=0",
        )

    def test_downloads_without_pdf_suffix(self):
        html = '<embed src="/downloads/2021/abc"></embed>'
        self.assertEqual(
            extract_pdf_url(html, "https://sci-hub.ee"),
            "https://sci-hub.ee/downloads/2021/abc",
        )

    def test_button(self):
        html = "<button onclick=\"location.href='/downloads/x.pdf'\">"
        self.assertEqual(
            extract_pdf_url(html, "https://sci-hub.se"),
            "https://sci-hub.se/downloads/x.pdf",
        )


class _FakeSession:
    """返回一段假 PDF 的流式响应，记录被请求的 URL。"""

    def __init__(self):
        self.requests: list[str] = []
        self.data = b"%PDF-1.4 fake content enough bytes"

    def get(self, url, *, strict=False, timeout=None):
        self.requests.append(url)
        return '<iframe src="/downloads/1.pdf"></iframe>'

    def open(self, url, *, strict=False, timeout=None):
        self.requests.append(url)

        class _Resp:
            headers = {"Content-Length": str(len(self.data))}

            def __init__(inner):
                inner._data = self.data
                inner._pos = 0

            def read(inner, n):
                chunk = inner._data[inner._pos : inner._pos + n]
                inner._pos += n
                return chunk

            def close(inner):
                pass

        return _Resp()


class TestBatchEngine(unittest.TestCase):
    def test_end_to_end_with_fake_session(self):
        import tempfile
        from pathlib import Path

        outdir = Path(tempfile.mkdtemp())
        fake = _FakeSession()
        engine = BatchEngine(
            outdir=str(outdir),
            naming_mode="doi",
            session=fake,
            use_metadata=False,  # 离线测试，不查 CrossRef
            concurrency=1,
        )
        events = []
        summary = engine.run(
            [Paper(doi="10.1063/1.1674820")],
            on_event=events.append,
        )
        self.assertEqual(summary.saved, 1, events)
        self.assertEqual(summary.failed, 0)
        # 至少请求过镜像页面 + 下载链接
        self.assertTrue(any("/10.1063/1.1674820" in u for u in fake.requests))
        # 产物落盘
        files = list(outdir.glob("*.pdf"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "10.1063_1.1674820.pdf")
        # done 事件一定发出
        self.assertTrue(any(e.type == "done" for e in events))


class _FailureSession:
    """可配置行为的假 session：返回指定 HTML 或抛 RequestError。"""

    def __init__(self, html: str = "", exc: RequestError | None = None):
        self.html = html
        self.exc = exc

    def get(self, url, *, strict=False, timeout=None):
        if self.exc is not None:
            raise self.exc
        return self.html

    def open(self, url, *, strict=False, timeout=None):
        if self.exc is not None:
            raise self.exc
        return None  # 失败场景不会走到这里


def _resolve(session) -> "ResolveResult":
    from scihub_dl.downloader import resolve_pdf_url

    return resolve_pdf_url(
        "10.1/x",
        pool=MirrorPool(["https://sci-hub.test"]),
        session=session,
        limiter=RateLimiter(interval=0.0),
        cancel_event=threading.Event(),
    )


class TestFailureReasons(unittest.TestCase):
    def test_not_found(self):
        r = _resolve(_FailureSession(html="<html>article not found</html>"))
        self.assertEqual(r.reason, "not_found")

    def test_captcha(self):
        r = _resolve(_FailureSession(html="<html>captcha required</html>"))
        self.assertEqual(r.reason, "captcha")

    def test_network_error(self):
        r = _resolve(_FailureSession(exc=RequestError("timeout")))
        self.assertEqual(r.reason, "network_error")

    def test_no_pdf(self):
        r = _resolve(_FailureSession(html="<html>nothing useful</html>"))
        self.assertEqual(r.reason, "no_pdf")

    def test_process_maps_network_error(self):
        import tempfile
        from pathlib import Path

        engine = BatchEngine(
            outdir=str(Path(tempfile.mkdtemp())),
            naming_mode="doi",
            session=_FailureSession(exc=RequestError("timeout")),
            use_metadata=False,
            concurrency=1,
        )
        statuses: list[str] = []
        status = engine._process(Paper(doi="10.1/x"), 0, lambda ev: statuses.append(ev.status))
        self.assertEqual(status, STATUS_NETWORK_ERROR)
        self.assertIn(STATUS_NETWORK_ERROR, statuses)


if __name__ == "__main__":
    unittest.main()
