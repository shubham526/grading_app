"""Opaque internal identifier helpers for v2.3.3 autograding."""

import uuid


def _new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex)


def generate_autograding_run_id():
    """Return a new opaque grading-run ID."""

    return _new_id("agrun")


def generate_test_bundle_id():
    """Return a new opaque instructor test-bundle ID."""

    return _new_id("bundle")


__all__ = [
    "generate_autograding_run_id",
    "generate_test_bundle_id",
]
