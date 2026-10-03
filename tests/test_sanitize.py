import threading
import unittest

from scihub_dl.sanitize import (
    MAX_STEM_BYTES,
    sanitize_filename,
    stem_budget,
    truncate_bytes,
    unique_stem,
)


class TestTruncateBytes(unittest.TestCase):
    def test_short_untouched(self):
        self.assertEqual(truncate_bytes("abc", 10), "abc")

    def test_ascii_cut(self):
        self.assertEqual(truncate_bytes("abcdefghij", 5), "abcde")

    def test_utf8_no_partial_codepoint(self):
        # 每个中文字符 3 字节，切到 4 字节应恰好留 1 个完整字，不产生乱码。
        self.assertEqual(truncate_bytes("中文标题", 4), "中")


class TestSanitize(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(sanitize_filename('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_control_chars(self):
        self.assertEqual(sanitize_filename("a\x00b\x1fc"), "a_b_c")

    def test_fullwidth_reserved_blocked(self):
        # NFKC 会把全角 ＣＯＮ 归一成 CON，保留名检查仍然命中。
        self.assertEqual(sanitize_filename("ＣＯＮ"), "_CON")

    def test_ascii_reserved(self):
        for name in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            self.assertEqual(sanitize_filename(name), "_" + name, name)

    def test_trailing_dot_space(self):
        self.assertEqual(sanitize_filename("title ."), "title")
        self.assertEqual(sanitize_filename("  title  "), "title")

    def test_empty(self):
        self.assertEqual(sanitize_filename(""), "untitled")
        self.assertEqual(sanitize_filename("***"), "untitled")

    def test_keeps_spaces(self):
        self.assertEqual(sanitize_filename("Weeks - 1971 - Title"),
                         "Weeks - 1971 - Title")

    def test_collapses_uscore(self):
        self.assertEqual(sanitize_filename("a__b___c"), "a_b_c")

    def test_byte_truncation(self):
        # 50 个中文字符 = 150 字节，超过 60 字节上限。
        s = sanitize_filename("字" * 50, max_bytes=60)
        self.assertLessEqual(len(s.encode("utf-8")), 60)


class TestUniqueStem(unittest.TestCase):
    def test_no_collision(self):
        used, lock = set(), threading.Lock()
        self.assertEqual(unique_stem("Title", ".pdf", used, lock), "Title")

    def test_collision_suffix(self):
        used, lock = {("Title.pdf").casefold()}, threading.Lock()
        self.assertEqual(unique_stem("Title", ".pdf", used, lock), "Title (2)")
        self.assertEqual(unique_stem("Title", ".pdf", used, lock), "Title (3)")

    def test_case_insensitive(self):
        # Windows 上 Title.pdf 与 title.pdf 是同一个文件。
        used, lock = {("Title.pdf").casefold()}, threading.Lock()
        self.assertEqual(unique_stem("title", ".pdf", used, lock), "title (2)")


class TestStemBudget(unittest.TestCase):
    def test_positive(self):
        self.assertGreaterEqual(stem_budget("/home/u/papers"), 40)

    def test_never_exceeds_max(self):
        self.assertLessEqual(stem_budget(""), MAX_STEM_BYTES)


if __name__ == "__main__":
    unittest.main()
