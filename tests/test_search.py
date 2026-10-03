"""检索功能的离线测试：全程不发真实网络请求。

假 session 返回固定的 CrossRef 响应体，因此这些用例可以直接跑在 CI 上，
也能锁住「字段缺失时怎么兜底」这类只有遇到脏数据才会暴露的行为。
"""

import json
import threading
import unittest

from scihub_dl.doi import normalize_doi
from scihub_dl.mirrors import MirrorPool
from scihub_dl.models import (
    AVAIL_AVAILABLE,
    AVAIL_CHECKING,
    AVAIL_NOT_FOUND,
    AVAIL_UNKNOWN,
)
from scihub_dl.net import RateLimiter, RequestError
from scihub_dl.search import (
    CROSSREF_SEARCH_API,
    MAX_ROWS,
    SearchError,
    SearchService,
    build_search_url,
    parse_pick,
    parse_search_results,
    probe_availability,
    search_works,
)


def _payload(items: list[dict]) -> str:
    """包一层 CrossRef 的外壳，只关心 items。"""
    return json.dumps({"status": "ok", "message-type": "work-list", "message": {"items": items}})


class _FakeSession:
    """按 URL 返回预设文本；``exc`` 不为空时抛网络错误。"""

    def __init__(self, text: str = "", exc: Exception | None = None):
        self.text = text
        self.exc = exc
        self.requests: list[str] = []

    def get(self, url, *, strict=False, timeout=None):
        self.requests.append(url)
        if self.exc is not None:
            raise self.exc
        return self.text

    def open(self, url, *, strict=False, timeout=None):
        raise AssertionError("检索链路不应调用 open()")


class TestBuildSearchUrl(unittest.TestCase):
    def test_defaults(self):
        url = build_search_url("hello world")
        self.assertTrue(url.startswith(CROSSREF_SEARCH_API + "?"))
        self.assertIn("query.bibliographic=hello+world", url)
        self.assertIn("rows=20", url)
        self.assertIn("sort=relevance", url)
        # 不带年份时不产生空的 filter 参数。
        self.assertNotIn("filter=", url)

    def test_year_filter_and_published_sort(self):
        url = build_search_url("x", year_from="2015", year_to="2024", sort="published")
        self.assertIn("sort=published", url)
        self.assertIn("order=desc", url)
        self.assertIn("from-pub-date%3A2015-01-01", url)
        self.assertIn("until-pub-date%3A2024-12-31", url)

    def test_invalid_year_and_rows_are_dropped_not_fatal(self):
        url = build_search_url("x", rows=9999, year_from="abc", year_to="")
        self.assertIn(f"rows={MAX_ROWS}", url)  # 收敛到上限而不是报错
        self.assertNotIn("filter=", url)

    def test_select_keeps_payload_small(self):
        # 不选字段的话，出版商会把整份参考文献表一起返回。
        self.assertIn("select=", build_search_url("x"))


class TestParseSearchResults(unittest.TestCase):
    def test_full_item(self):
        text = _payload(
            [
                {
                    "DOI": "10.1063/1.1674820",
                    "title": ["Role of Repulsive Forces in Liquids"],
                    "author": [{"given": "J. D.", "family": "Weeks"}],
                    "issued": {"date-parts": [[1971, 6, 15]]},
                    "container-title": ["The Journal of Chemical Physics"],
                    "URL": "https://doi.org/10.1063/1.1674820",
                }
            ]
        )
        results = parse_search_results(text)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.doi, "10.1063/1.1674820")
        self.assertEqual(r.title, "Role of Repulsive Forces in Liquids")
        self.assertEqual(r.author, "Weeks")
        self.assertEqual(r.year, "1971")
        self.assertEqual(r.journal, "The Journal of Chemical Physics")
        self.assertEqual(r.doi_url, "https://doi.org/10.1063/1.1674820")
        self.assertEqual(r.avail, AVAIL_UNKNOWN)

    def test_title_markup_and_whitespace_are_cleaned(self):
        text = _payload(
            [{"DOI": "10.1/x", "title": ["A <i>bold</i>\n  title &amp; more"]}]
        )
        r = parse_search_results(text)[0]
        self.assertEqual(r.title, "A bold title & more")

    def test_author_without_family_falls_back_to_name(self):
        # 团体作者/数据集只给 name（CrossRef 确实这么返回）。
        text = _payload(
            [{"DOI": "10.1/x", "title": ["t"], "author": [{"name": "National Toxicology Program"}]}]
        )
        self.assertEqual(parse_search_results(text)[0].author, "National Toxicology Program")

    def test_year_falls_back_through_published_fields(self):
        text = _payload(
            [
                {"DOI": "10.1/a", "title": ["a"], "published": {"date-parts": [[2019, 7]]}},
                {"DOI": "10.1/b", "title": ["b"], "published-online": {"date-parts": [[2020, 1, 2]]}},
            ]
        )
        years = [r.year for r in parse_search_results(text)]
        self.assertEqual(years, ["2019", "2020"])

    def test_item_without_doi_kept_but_not_selectable(self):
        text = _payload([{"title": ["A book chapter without DOI"]}])
        results = parse_search_results(text)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doi, "")
        self.assertFalse(results[0].selectable)
        self.assertEqual(results[0].doi_url, "")

    def test_item_without_title_and_doi_is_dropped(self):
        text = _payload([{"author": [{"family": "Nobody"}]}, {"DOI": "10.1/ok", "title": ["ok"]}])
        results = parse_search_results(text)
        self.assertEqual([r.doi for r in results], ["10.1/ok"])

    def test_missing_fields_do_not_crash(self):
        text = _payload([{"DOI": "10.1/x"}])
        r = parse_search_results(text)[0]
        self.assertEqual((r.title, r.author, r.year, r.journal), ("", "", "", ""))

    def test_broken_json_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_search_results("<html>502 Bad Gateway</html>")
        with self.assertRaises(ValueError):
            parse_search_results('{"status":"ok"}')

    def test_non_dict_items_are_ignored(self):
        text = _payload(["oops", 42, {"DOI": "10.1/ok", "title": ["ok"]}])
        self.assertEqual(len(parse_search_results(text)), 1)


class TestSelectable(unittest.TestCase):
    def _result(self, avail):
        from scihub_dl.models import SearchResult

        return SearchResult(doi="10.1/x", title="t", avail=avail)

    def test_not_found_is_not_selectable(self):
        self.assertFalse(self._result(AVAIL_NOT_FOUND).selectable)

    def test_unknown_and_checking_are_selectable(self):
        # 探测只是提示：拿不准的时候不该替用户做决定。
        self.assertTrue(self._result(AVAIL_UNKNOWN).selectable)
        self.assertTrue(self._result(AVAIL_CHECKING).selectable)
        self.assertTrue(self._result(AVAIL_AVAILABLE).selectable)

    def test_to_paper_carries_metadata(self):
        from scihub_dl.models import SearchResult

        paper = SearchResult(
            doi="10.1/x", title="T", author="Weeks", year="1971", journal="JCP"
        ).to_paper()
        self.assertTrue(paper.has_metadata())
        self.assertEqual((paper.doi, paper.author, paper.year, paper.journal),
                         ("10.1/x", "Weeks", "1971", "JCP"))


class TestSearchWorks(unittest.TestCase):
    def test_returns_results_and_uses_strict_session(self):
        session = _FakeSession(_payload([{"DOI": "10.1/x", "title": ["t"]}]))
        results = search_works("t", session=session)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(session.requests), 1)

    def test_empty_query_short_circuits(self):
        session = _FakeSession(_payload([]))
        self.assertEqual(search_works("   ", session=session), [])
        self.assertEqual(session.requests, [])  # 不发请求

    def test_network_error_becomes_search_error(self):
        with self.assertRaises(SearchError):
            search_works("t", session=_FakeSession(exc=RequestError("timeout")))

    def test_bad_payload_becomes_search_error(self):
        with self.assertRaises(SearchError):
            search_works("t", session=_FakeSession("not json"))


class TestParsePick(unittest.TestCase):
    def test_comma_list(self):
        self.assertEqual(parse_pick("1,3", 5), [1, 3])

    def test_range_and_spaces_and_duplicates(self):
        self.assertEqual(parse_pick("1-3 3,5", 6), [1, 2, 3, 5])

    def test_reversed_range(self):
        self.assertEqual(parse_pick("4-2", 5), [2, 3, 4])

    def test_out_of_range_and_garbage_ignored(self):
        self.assertEqual(parse_pick("0,2,99,abc,,", 3), [2])

    def test_empty(self):
        self.assertEqual(parse_pick("", 10), [])


class _MirrorSession:
    """模拟镜像响应：收录 / 未收录 / 验证码三种情况。"""

    def __init__(self, html: str):
        self.html = html

    def get(self, url, *, strict=False, timeout=None):
        return self.html

    def open(self, url, *, strict=False, timeout=None):
        raise AssertionError("探测不应走到下载")


def _probe(html: str, doi: str = "10.1/x"):
    return probe_availability(
        doi,
        pool=MirrorPool(["https://sci-hub.test"]),
        session=_MirrorSession(html),
        limiter=RateLimiter(interval=0.0),
        cancel_event=threading.Event(),
    )


class TestProbeAvailability(unittest.TestCase):
    def test_available(self):
        state, reason = _probe('<iframe src="/downloads/1.pdf"></iframe>')
        self.assertEqual((state, reason), (AVAIL_AVAILABLE, "ok"))

    def test_not_found(self):
        state, reason = _probe("<html>article not found</html>")
        self.assertEqual((state, reason), (AVAIL_NOT_FOUND, "not_found"))

    def test_captcha_is_unknown_not_unavailable(self):
        # 验证码说明「被拦住了」，不等于「没有这篇」，不能据此禁用勾选。
        state, reason = _probe("<html>captcha required</html>")
        self.assertEqual(state, AVAIL_UNKNOWN)
        self.assertEqual(reason, "captcha")

    def test_no_doi_is_unknown(self):
        state, reason = _probe("<html></html>", doi="")
        self.assertEqual((state, reason), (AVAIL_UNKNOWN, "no_doi"))


class TestSearchServiceProbe(unittest.TestCase):
    def test_probe_reports_each_row_and_resets_on_cancel(self):
        from scihub_dl.models import SearchResult

        results = [
            SearchResult(doi="10.1/a", title="a"),
            SearchResult(doi="", title="no doi"),  # 无 DOI：不该被探测
            SearchResult(doi="10.1/b", title="b"),
        ]
        cancel = threading.Event()
        service = SearchService(
            probe_session=_MirrorSession('<iframe src="/downloads/1.pdf"></iframe>'),
            mirrors=["https://sci-hub.test"],
            max_workers=2,
            cancel_event=cancel,
        )
        updates: list[tuple[int, str]] = []
        service.probe(results, on_update=lambda i, r: updates.append((i, r.avail)))

        self.assertEqual(results[0].avail, AVAIL_AVAILABLE)
        self.assertEqual(results[2].avail, AVAIL_AVAILABLE)
        self.assertEqual(results[1].avail, AVAIL_UNKNOWN)  # 未被探测
        self.assertIn((0, AVAIL_AVAILABLE), updates)
        self.assertIn((2, AVAIL_AVAILABLE), updates)
        self.assertNotIn(1, [i for i, _ in updates])

    def test_cancel_lands_every_row_in_a_definite_state(self):
        from scihub_dl.models import SearchResult

        cancel = threading.Event()
        cancel.set()  # 一开始就取消
        results = [SearchResult(doi="10.1/a", title="a")]
        service = SearchService(
            probe_session=_MirrorSession("<html></html>"),
            mirrors=["https://sci-hub.test"],
            cancel_event=cancel,
        )
        states: list[str] = []
        service.probe(results, on_update=lambda i, r: states.append(r.avail))
        self.assertEqual(results[0].avail, AVAIL_UNKNOWN)
        self.assertIn(AVAIL_CHECKING, states)  # 先亮「检查中」
        self.assertEqual(states[-1], AVAIL_UNKNOWN)  # 再落到确定状态


class TestDoiNormalizationInSearch(unittest.TestCase):
    def test_uppercase_doi_is_normalized_for_dedupe(self):
        text = _payload([{"DOI": "10.1063/1.1674820", "title": ["t"]}])
        r = parse_search_results(text)[0]
        self.assertEqual(r.doi, normalize_doi(r.doi))


if __name__ == "__main__":
    unittest.main()
