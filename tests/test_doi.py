import unittest

from scihub_dl.doi import extract_dois, extract_from_line, normalize_doi


class TestNormalize(unittest.TestCase):
    def test_bare(self):
        self.assertEqual(normalize_doi("10.1063/1.1674820"), "10.1063/1.1674820")

    def test_prefixes(self):
        for raw in (
            "https://doi.org/10.1063/1.1674820",
            "http://dx.doi.org/10.1063/1.1674820",
            "doi:10.1063/1.1674820",
            "DOI: 10.1063/1.1674820",
            "DOI：10.1063/1.1674820",
            "doi: https://doi.org/10.1063/1.1674820",
        ):
            self.assertEqual(normalize_doi(raw), "10.1063/1.1674820", raw)

    def test_trailing_punct(self):
        self.assertEqual(normalize_doi("10.1063/1.1674820."), "10.1063/1.1674820")
        self.assertEqual(normalize_doi("10.1063/1.1674820,"), "10.1063/1.1674820")

    def test_balanced_paren_kept(self):
        # 结尾 ")" 是 DOI 自身配平的括号，不能剥。
        self.assertEqual(
            normalize_doi("10.1016/S0022-2836(05)80360-2"),
            "10.1016/s0022-2836(05)80360-2",
        )

    def test_sici_doi_survives(self):
        # 经典 Wiley SICI DOI，含 < > ; : 必须原样保留。
        sici = "10.1002/(SICI)1097-0258(19970815)16:15<1705::AID-SIM609>3.0.CO;2-Y"
        self.assertEqual(normalize_doi(sici), sici.lower())

    def test_lowercases(self):
        self.assertEqual(normalize_doi("10.1103/PhysRevLett.126.011101"),
                         "10.1103/physrevlett.126.011101")

    def test_non_doi(self):
        for bad in ("", "   ", "not a doi", "https://example.com/10.1/x",
                    "10.1/short", "10.1234567890/registrant-too-long"):
            self.assertIsNone(normalize_doi(bad), bad)


class TestExtractFromLine(unittest.TestCase):
    def test_whole_line_sici(self):
        sici = "10.1002/(SICI)1097-0258(19970815)16:15<1705::AID-SIM609>3.0.CO;2-Y"
        self.assertEqual(extract_from_line(sici), [sici.lower()])

    def test_plain_line(self):
        self.assertEqual(extract_from_line("10.1063/1.1674820"),
                         ["10.1063/1.1674820"])

    def test_prose(self):
        line = "see 10.1016/S0022-2836(05)80360-2 and 10.1103/PhysRevLett.126.011101."
        self.assertEqual(
            extract_from_line(line),
            ["10.1016/s0022-2836(05)80360-2", "10.1103/physrevlett.126.011101"],
        )

    def test_markdown_link(self):
        line = "- **DOI**: [10.1021/ja01234](https://doi.org/10.1021/ja01234)"
        self.assertEqual(extract_from_line(line), ["10.1021/ja01234"])

    def test_two_links(self):
        line = "[a](https://doi.org/10.1063/1.1674820) [b](https://doi.org/10.1038/nature12373)"
        self.assertEqual(
            extract_from_line(line),
            ["10.1063/1.1674820", "10.1038/nature12373"],
        )

    def test_empty(self):
        self.assertEqual(extract_from_line(""), [])
        self.assertEqual(extract_from_line("no doi here"), [])


class TestExtractDois(unittest.TestCase):
    def test_multiline_dedup(self):
        text = (
            "10.1063/1.1674820\n"
            "https://doi.org/10.1063/1.1674820\n"  # 重复
            "10.1038/nature12373\n"
        )
        self.assertEqual(
            extract_dois(text),
            ["10.1063/1.1674820", "10.1038/nature12373"],
        )


if __name__ == "__main__":
    unittest.main()
