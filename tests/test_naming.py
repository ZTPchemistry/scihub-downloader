import unittest

from scihub_dl.models import Paper
from scihub_dl.naming import TEMPLATES, build_filename, render_name


class TestRenderName(unittest.TestCase):
    def test_title(self):
        self.assertEqual(render_name("{title}", title="Foo"), "Foo")

    def test_title_falls_back_to_doi(self):
        self.assertEqual(render_name("{title}", doi="10.1/x"), "10.1/x")

    def test_empty_fields_tidied(self):
        # author 为空时，" - 1971 - Title" 首部的空档应被清掉。
        self.assertEqual(
            render_name("{author} - {year} - {title}", year="1971", title="T"),
            "1971 - T",
        )

    def test_all_empty(self):
        self.assertEqual(render_name("{author} - {year} - {title}"), "")

    def test_unknown_placeholder_literal(self):
        # 未知占位符不抛异常，原样保留。
        self.assertEqual(render_name("{title} {bogus}", title="T"), "T {bogus}")


class TestBuildFilename(unittest.TestCase):
    def _paper(self, **kw):
        return Paper(doi="10.1063/1.1674820", **kw)

    def test_doi_mode_slash_to_underscore(self):
        p = self._paper(title="WCA Theory")
        self.assertEqual(build_filename(p, "doi"), "10.1063_1.1674820")

    def test_title_mode(self):
        p = self._paper(title='A/B:c*d?e"f<g>h|i')
        self.assertEqual(build_filename(p, "title"), "A_B_c_d_e_f_g_h_i")

    def test_author_year_title(self):
        p = self._paper(title="Role of Repulsive Forces", author="Weeks", year="1971")
        self.assertEqual(
            build_filename(p, "author"),
            "Weeks - 1971 - Role of Repulsive Forces",
        )

    def test_no_title_falls_back(self):
        p = self._paper()  # 无 title
        self.assertEqual(build_filename(p, "title"), "10.1063_1.1674820")

    def test_custom(self):
        p = self._paper(title="Foo", journal="J Chem", year="2020")
        self.assertEqual(
            build_filename(p, "custom", "{journal} - {year}"),
            "J Chem - 2020",
        )

    def test_presets_consistent(self):
        # 所有预设模板键都存在且可渲染。
        for mode, tpl in TEMPLATES.items():
            self.assertIsInstance(tpl, str)
            self.assertTrue(build_filename(self._paper(title="X"), mode))


if __name__ == "__main__":
    unittest.main()
