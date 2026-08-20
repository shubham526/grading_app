"""Release-version regression for v2.3.4.1."""

import unittest

import src


class TestPackageVersion(unittest.TestCase):
    def test_package_version_is_v2_3_4_1(self):
        self.assertEqual(src.__version__, "2.3.4.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
