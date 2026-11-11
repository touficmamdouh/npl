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
            "packaging/npl.svg",
            "packaging/build-macos-app.sh",
            "packaging/systemd/npl-usage.service",
            "packaging/macos/com.npl.usage.plist",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_python_distribution_includes_usage_modules(self):
        pyproject = (ROOT / "pyproject.toml").read_text()
        for module in (
            "usage_store",
            "usage_collectors",
            "usage_formatting",
            "usage_services",
        ):
            with self.subTest(module=module):
                self.assertIn(f'"{module}"', pyproject)

    def test_host_collectors_are_not_runtime_python_dependencies(self):
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertNotIn('"nethogs"', pyproject)
        self.assertNotIn('"nettop"', pyproject)

    def test_linux_installer_grants_nethogs_capture_capabilities(self):
        installer = (ROOT / "install.sh").read_text()

        self.assertIn("libcap2-bin", installer)
        self.assertIn("cap_net_admin,cap_net_raw+eip", installer)


if __name__ == "__main__":
    unittest.main()
