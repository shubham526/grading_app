"""Release-version regression for v2.3.3."""

import unittest

import src


class TestPackageVersion(unittest.TestCase):
    def test_package_version_is_v2_3_3(self):
        self.assertEqual(src.__version__, "2.3.3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
