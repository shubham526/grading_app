"""Release-version regression for v2.1.0."""

import src


def test_package_version_is_v2_1_0():
    assert src.__version__ == "2.1.0"
