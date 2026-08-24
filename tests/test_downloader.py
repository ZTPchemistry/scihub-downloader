"""下载引擎的离线测试：用假 session 验证整条流程，不发真实网络请求。"""

import threading
import unittest

from scihub_dl.downloader import BatchEngine, extract_pdf_url
from scihub_dl.models import Paper


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


if __name__ == "__main__":
    unittest.main()
