import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class TestPackagingScaffolding(unittest.TestCase):
    def test_packaging_files_exist(self):
        for relative in (
            "pyproject.toml",
            "packaging/npl.spec",
            "packaging/build-appimage.sh",
            "packaging/AppRun",
            "packaging/npl.desktop",
            "packaging/build-macos-app.sh",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())


if __name__ == "__main__":
    unittest.main()
