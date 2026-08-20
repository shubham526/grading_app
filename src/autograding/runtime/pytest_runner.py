#!/usr/bin/env python3
"""Container-side structured pytest runner for v2.3.3 Commit 6.

This module is copied into the ephemeral Docker runtime directory and executed
inside the isolated grading container.  It is deliberately self-contained
apart from pytest and the Python standard library.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tokenize
import signal
import sys
import traceback as traceback_module

import pytest


PROTOCOL_SCHEMA_VERSION = "1.0"
CONFIG_SCHEMA_VERSION = "1.0"
DEFAULT_MAX_CAPTURE_BYTES = 16384
DEFAULT_MAX_TRACEBACK_BYTES = 32768


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate_utf8(text, max_bytes):
    value = "" if text is None else str(text)
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return value, False
    clipped = encoded[:max_bytes]
    while True:
        try:
            return clipped.decode("utf-8", errors="strict"), True
        except UnicodeDecodeError as exc:
            clipped = clipped[:exc.start]
            if not clipped:
                return "", True


def _normalize_nodeid(value):
    return str(value or "").replace("\\", "/").lstrip("./")


def _function_name(nodeid):
    parts = _normalize_nodeid(nodeid).split("::")
    if len(parts) < 2:
        return ""
    return parts[-1].split("[", 1)[0]


def _matches_selector(nodeid, selector):
    nodeid = _normalize_nodeid(nodeid)
    selector = _normalize_nodeid(selector)
    if "::" not in selector:
        return _function_name(nodeid) == selector
    if nodeid == selector:
        return True
    # A selector without a parameter suffix represents every collected
    # parameter case for that declared test function/method.
    if "[" not in selector and nodeid.startswith(selector + "["):
        return True
    return False


class GradingTestTimeout(Exception):
    pass


class StructuredPlugin:
    def __init__(self, config):
        self.config = config
        self.tests = tuple(config.get("tests") or ())
        self.capture_bytes = int(config.get("max_capture_bytes") or DEFAULT_MAX_CAPTURE_BYTES)
        self.traceback_bytes = int(config.get("max_traceback_bytes") or DEFAULT_MAX_TRACEBACK_BYTES)
        self.started_at = _utc_now_iso()
        self.finished_at = None
        self.collected_count = 0
        self.selected_count = 0
        self.deselected_count = 0
        self.selection_errors = []
        self.collection_errors = []
        self.node_to_test = {}
        self.item_records = {}
        self.timeout_nodeids = set()
        self.session_exitstatus = None

    def _record_for(self, nodeid):
        record = self.item_records.get(nodeid)
        if record is None:
            record = {
                "nodeid": nodeid,
                "status": "pending",
                "duration_ms": 0,
                "message": None,
                "traceback": None,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "timeout_seconds": None,
                "phases": [],
            }
            self.item_records[nodeid] = record
        return record

    def pytest_collection_modifyitems(self, session, config, items):
        self.collected_count = len(items)
        selected = []
        deselected = []
        matched_by_test = {str(item.get("test_id")): [] for item in self.tests}

        for item in items:
            matches = []
            for test in self.tests:
                selector = str(test.get("selector") or test.get("test_id") or "").strip()
                if selector and _matches_selector(item.nodeid, selector):
                    matches.append(test)
            if len(matches) == 1:
                test = matches[0]
                self.node_to_test[item.nodeid] = test
                matched_by_test[str(test.get("test_id"))].append(item.nodeid)
                selected.append(item)
            elif len(matches) == 0:
                deselected.append(item)
            else:
                self.selection_errors.append(
                    "Collected pytest item %r matches multiple configured tests: %s"
                    % (item.nodeid, ", ".join(str(m.get("test_id")) for m in matches))
                )
                deselected.append(item)

        for test in self.tests:
            test_id = str(test.get("test_id"))
            if not matched_by_test.get(test_id):
                self.selection_errors.append(
                    "Configured test %r did not match any collected pytest item" % test_id
                )

        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = selected
        self.selected_count = len(selected)
        self.deselected_count = len(deselected)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        # hookwrapper=True is intentionally used instead of the newer
        # wrapper=True spelling.  The dedicated Docker runtime uses a pinned
        # modern pytest, but this runner is also exercised by a host-side unit
        # test where the instructor's Python environment may contain an older
        # pytest/pluggy combination.  hookwrapper=True remains compatible
        # across both generations.
        test = self.node_to_test.get(item.nodeid) or {}
        raw_timeout = test.get("timeout_seconds")
        if raw_timeout is None:
            yield
            return

        timeout = float(raw_timeout)
        if timeout <= 0:
            yield
            return
        if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
            yield
            return

        previous_handler = signal.getsignal(signal.SIGALRM)

        def _handler(signum, frame):
            self.timeout_nodeids.add(item.nodeid)
            raise GradingTestTimeout(
                "Configured test timeout exceeded after %.3f seconds" % timeout
            )

        signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def pytest_runtest_logreport(self, report):
        if report.nodeid not in self.node_to_test:
            return
        record = self._record_for(report.nodeid)
        duration = getattr(report, "duration", 0.0) or 0.0
        record["duration_ms"] += max(0, int(round(float(duration) * 1000.0)))
        record["phases"].append({"when": report.when, "outcome": report.outcome})

        stdout, stdout_truncated = _truncate_utf8(report.capstdout, self.capture_bytes)
        stderr, stderr_truncated = _truncate_utf8(report.capstderr, self.capture_bytes)
        if stdout:
            record["stdout"] = stdout
            record["stdout_truncated"] = bool(stdout_truncated)
        if stderr:
            record["stderr"] = stderr
            record["stderr_truncated"] = bool(stderr_truncated)

        was_xfail = getattr(report, "wasxfail", None)
        timed_out = report.nodeid in self.timeout_nodeids
        if getattr(report, "when", None) == "call" and report.failed and timed_out:
            record["status"] = "timeout"
            record["timeout_seconds"] = (self.node_to_test.get(report.nodeid) or {}).get("timeout_seconds")
        elif report.when in ("setup", "teardown") and report.failed:
            record["status"] = "error"
        elif report.when == "call":
            if report.skipped and was_xfail:
                record["status"] = "xfail"
            elif report.passed and was_xfail:
                record["status"] = "xpass"
            elif report.skipped:
                record["status"] = "skipped"
            elif report.failed:
                record["status"] = "failed"
            elif report.passed:
                record["status"] = "passed"

        if report.failed:
            longrepr = report.longreprtext
            clipped, _ = _truncate_utf8(longrepr, self.traceback_bytes)
            record["traceback"] = clipped or None
            lines = [line.strip() for line in clipped.splitlines() if line.strip()]
            record["message"] = lines[-1] if lines else "pytest test failed"

    def pytest_collectreport(self, report):
        if report.failed:
            text = getattr(report, "longrepr", None)
            value = str(text) if text is not None else "pytest collection failed"
            clipped, _ = _truncate_utf8(value, self.traceback_bytes)
            self.collection_errors.append(
                {"nodeid": _normalize_nodeid(report.nodeid), "message": clipped}
            )

    def pytest_sessionfinish(self, session, exitstatus):
        self.finished_at = _utc_now_iso()
        try:
            self.session_exitstatus = int(exitstatus)
        except Exception:
            self.session_exitstatus = None

    def protocol_payload(self):
        grouped = []
        severity = {
            "error": 70,
            "timeout": 60,
            "failed": 50,
            "xpass": 40,
            "skipped": 30,
            "xfail": 20,
            "passed": 10,
            "pending": 0,
        }
        for test in self.tests:
            test_id = str(test.get("test_id"))
            item_records = [
                self.item_records[nodeid]
                for nodeid, mapped in self.node_to_test.items()
                if str(mapped.get("test_id")) == test_id and nodeid in self.item_records
            ]
            if item_records:
                status = max(
                    (record.get("status", "pending") for record in item_records),
                    key=lambda value: severity.get(value, 0),
                )
                duration_ms = sum(int(record.get("duration_ms") or 0) for record in item_records)
                stdout = "".join(record.get("stdout") or "" for record in item_records)
                stderr = "".join(record.get("stderr") or "" for record in item_records)
                stdout, stdout_truncated = _truncate_utf8(stdout, self.capture_bytes)
                stderr, stderr_truncated = _truncate_utf8(stderr, self.capture_bytes)
                failing = next(
                    (
                        record
                        for record in item_records
                        if record.get("status") in ("error", "timeout", "failed", "xpass")
                    ),
                    None,
                )
                message = failing.get("message") if failing else None
                tb = failing.get("traceback") if failing else None
            else:
                status = "pending"
                duration_ms = 0
                stdout = ""
                stderr = ""
                stdout_truncated = False
                stderr_truncated = False
                message = None
                tb = None

            grouped.append(
                {
                    "test_id": test_id,
                    "selector": test.get("selector"),
                    "visibility": test.get("visibility", "hidden"),
                    "group_id": test.get("group_id"),
                    "display_name": test.get("display_name"),
                    "status": status,
                    "duration_ms": duration_ms,
                    "message": message,
                    "traceback": tb,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                    "nodeids": [record.get("nodeid") for record in item_records],
                    "item_count": len(item_records),
                    "timeout_seconds": test.get("timeout_seconds"),
                }
            )

        return {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "runner": "pytest",
            "pytest_version": getattr(pytest, "__version__", None),
            "started_at": self.started_at,
            "finished_at": self.finished_at or _utc_now_iso(),
            "pytest_exit_code": self.session_exitstatus,
            "collected_count": self.collected_count,
            "selected_count": self.selected_count,
            "deselected_count": self.deselected_count,
            "selection_errors": list(self.selection_errors),
            "collection_errors": list(self.collection_errors),
            "tests": grouped,
        }


def _write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(target))


def _load_config(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pytest runner config must be a JSON object")
    if str(payload.get("schema_version")) != CONFIG_SCHEMA_VERSION:
        raise ValueError("unsupported pytest runner config schema")
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("pytest runner config requires at least one test")
    return payload


def _student_syntax_preflight(submission_root):
    errors = []
    for path in sorted(Path(submission_root).rglob("*.py")):
        try:
            with tokenize.open(str(path)) as handle:
                source = handle.read()
            compile(source, str(path), "exec", dont_inherit=True)
        except (SyntaxError, UnicodeError, OSError) as exc:
            errors.append({"path": str(path.relative_to(submission_root)), "message": str(exc)})
    return errors


def _student_syntax_payload(config, errors):
    now = _utc_now_iso()
    tests = []
    message = errors[0]["message"] if errors else "student syntax preflight failed"
    for test in config.get("tests") or ():
        tests.append(
            {
                "test_id": test.get("test_id"),
                "selector": test.get("selector"),
                "visibility": test.get("visibility", "hidden"),
                "group_id": test.get("group_id"),
                "display_name": test.get("display_name"),
                "status": "error",
                "duration_ms": 0,
                "message": "Student submission has a Python syntax error.",
                "traceback": message,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "nodeids": [],
                "item_count": 0,
                "timeout_seconds": test.get("timeout_seconds"),
            }
        )
    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "runner": "pytest",
        "pytest_version": getattr(pytest, "__version__", None),
        "started_at": now,
        "finished_at": now,
        "pytest_exit_code": 1,
        "collected_count": 0,
        "selected_count": 0,
        "deselected_count": 0,
        "selection_errors": [],
        "collection_errors": [],
        "student_preflight_errors": errors,
        "tests": tests,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--submission-root", default="/workspace/submission")
    parser.add_argument("--grader-root", default="/workspace/grader")
    args = parser.parse_args(argv)

    try:
        config = _load_config(args.config)
    except Exception:
        payload = {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "runner": "pytest",
            "pytest_version": getattr(pytest, "__version__", None),
            "started_at": _utc_now_iso(),
            "finished_at": _utc_now_iso(),
            "pytest_exit_code": 4,
            "collected_count": 0,
            "selected_count": 0,
            "deselected_count": 0,
            "selection_errors": [],
            "collection_errors": [
                {"nodeid": "", "message": traceback_module.format_exc()}
            ],
            "tests": [],
            "runner_configuration_error": True,
        }
        _write_json(args.output, payload)
        return 4

    syntax_errors = _student_syntax_preflight(args.submission_root)
    if syntax_errors:
        _write_json(args.output, _student_syntax_payload(config, syntax_errors))
        return 1

    # Student imports should resolve before grader support modules.  The grader
    # root is included so instructor tests may import support helpers.
    sys.path.insert(0, str(Path(args.submission_root)))
    support = Path(args.grader_root) / "support"
    if support.is_dir():
        sys.path.insert(1, str(support))
    sys.path.insert(2, str(Path(args.grader_root)))

    plugin = StructuredPlugin(config)
    pytest_args = [
        "-qq",
        "--disable-warnings",
        "--tb=no",
        "--capture=fd",
        "--show-capture=no",
        "--no-summary",
        "--rootdir=%s" % str(Path(args.grader_root)),
        str(Path(args.grader_root) / "tests"),
    ]
    try:
        exit_code = pytest.main(pytest_args, plugins=[plugin])
    except BaseException:
        payload = plugin.protocol_payload()
        payload["runner_internal_error"] = traceback_module.format_exc()
        _write_json(args.output, payload)
        return 3

    payload = plugin.protocol_payload()
    if payload.get("pytest_exit_code") is None:
        try:
            payload["pytest_exit_code"] = int(exit_code)
        except Exception:
            payload["pytest_exit_code"] = None
    _write_json(args.output, payload)
    try:
        return int(exit_code)
    except Exception:
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
