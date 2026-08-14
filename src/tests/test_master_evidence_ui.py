"""Tests for v2.2.1 Master ABET Evidence UI integration."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_WINDOW_PATH = REPO_ROOT / "src" / "ui" / "main_window.py"
DIALOG_PATH = REPO_ROOT / "src" / "ui" / "dialogs" / "master_evidence_export_dialog.py"


class TestMasterEvidenceMainWindowWiring(unittest.TestCase):
    """Source-level checks remain useful even in non-Qt CI environments."""

    def test_reports_menu_contains_master_evidence_action(self):
        source = MAIN_WINDOW_PATH.read_text(encoding="utf-8")
        self.assertIn('"Master ABET Evidence Sheet"', source)
        self.assertIn("reports_menu.addAction(self.master_evidence_btn)", source)
        self.assertIn(
            "self.master_evidence_btn.triggered.connect(self.show_master_abet_evidence_export)",
            source,
        )

    def test_main_window_opens_dedicated_dialog_and_prefills_current_context(self):
        source = MAIN_WINDOW_PATH.read_text(encoding="utf-8")
        self.assertIn("from src.ui.dialogs.master_evidence_export_dialog import", source)
        self.assertIn("def show_master_abet_evidence_export(self):", source)
        self.assertIn('"rubric_path": self.rubric_file_path or ""', source)
        self.assertIn('"assessments_dir": self.assessments_dir or ""', source)
        self.assertIn("MasterEvidenceExportDialog(", source)

    def test_dialog_calls_shared_backend_not_cli(self):
        source = DIALOG_PATH.read_text(encoding="utf-8")
        self.assertIn("from src.tools.master_evidence_export import", source)
        self.assertIn("collect_master_evidence_for_assignment", source)
        self.assertIn("collect_master_evidence_for_semester", source)
        self.assertIn("export_master_evidence", source)
        self.assertNotIn("tools.export_master_abet_evidence", source)

    def test_dialog_body_is_scrollable_and_footer_is_outside_scroll_area(self):
        source = DIALOG_PATH.read_text(encoding="utf-8")
        self.assertIn("self.setMinimumSize(720, 520)", source)
        self.assertIn("self.setSizeGripEnabled(True)", source)
        self.assertIn("self.body_scroll = QScrollArea(self)", source)
        self.assertIn("outer.addWidget(self.body_scroll, 1)", source)
        # Footer actions are added after the scrollable body so Export/Close
        # remain reachable on laptop-sized displays.
        self.assertLess(
            source.index("outer.addWidget(self.body_scroll, 1)"),
            source.index("outer.addLayout(action_row)"),
        )

    def test_result_summary_has_its_own_scrollable_viewport(self):
        source = DIALOG_PATH.read_text(encoding="utf-8")
        self.assertIn("self.result_scroll = QScrollArea(self.result_group)", source)
        self.assertIn("self.result_scroll.setWidget(self.result_label)", source)
        self.assertIn("self.result_scroll.setMinimumHeight(130)", source)


try:
    import PyQt5
    from PyQt5.QtWidgets import QApplication

    _QT_AVAILABLE = not isinstance(PyQt5, Mock) and not isinstance(QApplication, Mock)
except (ImportError, ModuleNotFoundError):
    QApplication = None
    _QT_AVAILABLE = False


@unittest.skipUnless(_QT_AVAILABLE, "PyQt5 is required for master-evidence UI tests")
class TestMasterEvidenceExportDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, **defaults):
        from src.ui.dialogs.master_evidence_export_dialog import MasterEvidenceExportDialog

        dialog = MasterEvidenceExportDialog(assignment_defaults=defaults)
        self.addCleanup(dialog.close)
        return dialog

    def test_default_mode_formats_and_policy_match_design(self):
        dialog = self._dialog()
        self.assertTrue(dialog.semester_mode_radio.isChecked())
        self.assertEqual(dialog.selected_formats(), ["csv", "xlsx", "json"])
        self.assertEqual(dialog.evidence_policy_combo.currentText(), "counted_only")
        self.assertFalse(dialog.include_excluded_checkbox.isChecked())

    def test_assignment_defaults_are_prefilled(self):
        dialog = self._dialog(
            rubric_path="/tmp/ps3.json",
            assessments_dir="/tmp/assessments/ps3",
            assignment_id="PS3",
            assignment_title="Dynamic Programming",
            course_code="CS 2500",
            semester="Fall 2026",
            section="104",
        )
        self.assertEqual(dialog.rubric_edit.text(), "/tmp/ps3.json")
        self.assertEqual(dialog.assessments_dir_edit.text(), "/tmp/assessments/ps3")
        self.assertEqual(dialog.assignment_id_edit.text(), "PS3")
        self.assertEqual(dialog.assignment_title_edit.text(), "Dynamic Programming")
        self.assertEqual(dialog.course_code_edit.text(), "CS 2500")
        self.assertEqual(dialog.semester_edit.text(), "Fall 2026")
        self.assertEqual(dialog.section_edit.text(), "104")

    def test_mode_switch_exposes_single_assignment_form(self):
        dialog = self._dialog()
        dialog.show()
        QApplication.processEvents()
        self.assertFalse(dialog.assignment_group.isVisible())
        dialog.assignment_mode_radio.setChecked(True)
        QApplication.processEvents()
        self.assertTrue(dialog.assignment_group.isVisible())
        self.assertFalse(dialog.semester_group.isVisible())

    def test_validation_requires_format_output_and_mode_source(self):
        dialog = self._dialog()
        dialog.csv_checkbox.setChecked(False)
        dialog.xlsx_checkbox.setChecked(False)
        dialog.json_checkbox.setChecked(False)
        self.assertIn("format", dialog.validation_error().lower())

        dialog.csv_checkbox.setChecked(True)
        self.assertIn("output", dialog.validation_error().lower())

        dialog.output_dir_edit.setText("/tmp/out")
        self.assertIn("semester config", dialog.validation_error().lower())

    def test_assignment_mode_runs_real_csv_export_through_shared_backend(self):
        dialog = self._dialog()
        dialog.assignment_mode_radio.setChecked(True)
        dialog.xlsx_checkbox.setChecked(False)
        dialog.json_checkbox.setChecked(False)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rubric = root / "rubric.json"
            assessments = root / "assessments"
            output = root / "out"
            assessments.mkdir()

            rubric.write_text(
                json.dumps({
                    "schema_version": "2.0",
                    "criteria": [{
                        "id": "Q1_RUNTIME",
                        "question_id": "Q1",
                        "title": "Runtime",
                        "points": 4,
                        "course_outcomes": ["LO1"],
                        "program_outcomes": ["SO1"],
                        "abet_outcomes": ["SO1"],
                        "assessment_tags": ["runtime"],
                    }],
                }),
                encoding="utf-8",
            )
            (assessments / "alice.json").write_text(
                json.dumps({
                    "student_id": "alice",
                    "student_name": "Alice Smith",
                    "criteria": [{
                        "id": "Q1_RUNTIME",
                        "question_id": "Q1",
                        "title": "Runtime",
                        "points_awarded": 3,
                        "points_possible": 4,
                        "selected": True,
                        "counted": True,
                        "course_outcomes": ["LO1"],
                        "program_outcomes": ["SO1"],
                        "abet_outcomes": ["SO1"],
                        "assessment_tags": ["runtime"],
                    }],
                }),
                encoding="utf-8",
            )

            dialog.rubric_edit.setText(str(rubric))
            dialog.assessments_dir_edit.setText(str(assessments))
            dialog.output_dir_edit.setText(str(output))
            dialog.assignment_id_edit.setText("PS1")
            dialog.assignment_title_edit.setText("Runtime Analysis")
            dialog.course_code_edit.setText("CS 2500")
            dialog.semester_edit.setText("Fall 2026")

            result = dialog.perform_export()

            self.assertEqual(len(result["rows"]), 1)
            self.assertEqual(result["rows"][0]["student_id"], "alice")
            self.assertTrue((output / "master_abet_evidence.csv").is_file())
            self.assertEqual(result["paths"]["csv"], str((output / "master_abet_evidence.csv").resolve()))

    def test_semester_mode_passes_config_directory_as_relative_path_base(self):
        dialog = self._dialog()
        dialog.csv_checkbox.setChecked(True)
        dialog.xlsx_checkbox.setChecked(False)
        dialog.json_checkbox.setChecked(False)

        from src.tools.master_evidence_export import MasterEvidenceBuildResult

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "semester.json"
            output = root / "out"
            config.write_text(
                json.dumps({
                    "semester": "Fall 2026",
                    "course_code": "CS 2500",
                    "course_name": "Algorithms",
                    "section": "104",
                    "assignments": [],
                }),
                encoding="utf-8",
            )
            dialog.semester_config_edit.setText(str(config))
            dialog.output_dir_edit.setText(str(output))

            empty = MasterEvidenceBuildResult(rows=[], warnings=[])
            with patch(
                "src.ui.dialogs.master_evidence_export_dialog.collect_master_evidence_for_semester",
                return_value=empty,
            ) as collect, patch(
                "src.ui.dialogs.master_evidence_export_dialog.export_master_evidence",
                return_value={"csv": str(output / "master_abet_evidence.csv")},
            ) as export:
                dialog.perform_export()

            self.assertEqual(collect.call_args.kwargs["base_dir"], str(root.resolve()))
            self.assertEqual(export.call_args.kwargs["course_meta"]["course_code"], "CS 2500")

    def test_single_assignment_form_can_shrink_with_scroll_and_keep_export_visible(self):
        dialog = self._dialog()
        dialog.assignment_mode_radio.setChecked(True)
        dialog.resize(760, 540)
        dialog.show()
        QApplication.processEvents()

        self.assertTrue(dialog.isSizeGripEnabled())
        self.assertTrue(dialog.body_scroll.widgetResizable())
        self.assertTrue(dialog.export_button.isVisible())
        # The long single-assignment form should scroll instead of forcing the
        # entire dialog beyond the display.
        self.assertGreater(dialog.body_scroll.verticalScrollBar().maximum(), 0)

    def test_result_panel_reports_files_unavailable_xlsx_and_warning_count(self):
        dialog = self._dialog()
        dialog._show_export_result({
            "paths": {
                "csv": "/tmp/out/master_abet_evidence.csv",
                "xlsx": None,
                "json": "/tmp/out/master_abet_evidence.json",
            },
            "warnings": [{"code": "missing_submission_meta", "message": "optional"}],
            "rows": [],
            "output_dir": "/tmp/out",
        })
        text = dialog.result_label.text()
        self.assertIn("Master evidence export complete", text)
        self.assertIn("XLSX: unavailable", text)
        self.assertIn("Warnings: 1", text)
        self.assertTrue(dialog.view_warnings_button.isEnabled())
        self.assertTrue(dialog.open_folder_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
