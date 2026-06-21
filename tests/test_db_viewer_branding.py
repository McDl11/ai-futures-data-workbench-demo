import unittest

from apps.db_viewer.app import page


class DbViewerBrandingTests(unittest.TestCase):
    def test_page_header_includes_public_demo_author_identity(self):
        html = page("总览", "/", "<h1>总览</h1>")

        self.assertIn("Public Demo · mach (@McDl11)", html)


if __name__ == "__main__":
    unittest.main()
