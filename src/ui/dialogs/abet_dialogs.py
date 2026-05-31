"""
ABET Dialogs — Rubric Grading Tool
====================================

Phase 4 UI dialogs for ABET/program-outcome assessment:

ABETMappingDialog
    Full rubric-outcome mapping UI with:
    - Columns: ID, Title, Points, Course LOs, Program/ABET SOs, Tags, Status
    - Auto-map from title keywords
    - Apply course profile defaults
    - Validate mappings
    - Save mappings into rubric (embedded) or to external file
    - Import / export / clear

ABETReportDialog
    Assignment-level report generator with:
    - Embedded-outcome support (no mapping file required)
    - Profile selection
    - Evidence policy selector
    - Validation summary before generation
    - JSON + CSV + XLSX export

ABETResultsDialog
    Display report results with colour-coded tables.

SemesterABETReportDialog
    Semester-level aggregation across multiple assignments:
    - Config-file or folder-scan mode
    - Progress display
    - All required output tables
    - Export to XLSX / CSV
"""

import json
import os
from datetime import datetime
from typing import Dict

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QProgressDialog, QTabWidget, QSplitter,
)

# ABET CS outcomes (2025-2026) — used when no profile is loaded
ABET_CS_OUTCOMES = {
    "SO1": "Analyze a complex computing problem and to apply principles of computing and other relevant disciplines to identify solutions",
    "SO2": "Design, implement, and evaluate a computing-based solution to meet a given set of computing requirements",
    "SO3": "Communicate effectively in a variety of professional contexts",
    "SO4": "Recognize professional responsibilities and make informed judgments in computing practice based on legal and ethical principles",
    "SO5": "Function effectively as a member or leader of a team",
    "SO6": "Apply computer science theory and software development fundamentals to produce computing-based solutions",
}


# ===========================================================================
# ABETMappingDialog  (Phase 4 full version)
# ===========================================================================

class ABETMappingDialog(QDialog):
    """
    Full ABET/program-outcome mapping dialog.

    Features (per Change #9):
    - Table columns: ID | Title | Points | Course LOs | ABET SOs | Tags | Status
    - Buttons: Auto-map from title | Apply profile defaults | Validate |
               Save into rubric | Export mapping | Import mapping | Clear
    - Profile-driven keyword auto-mapping
    - Writes program_outcomes (canonical) + abet_outcomes alias into rubric
    """

    def __init__(self, rubric_data: dict, parent=None, profile=None):
        super().__init__(parent)
        self.rubric_data = rubric_data
        self.profile     = profile
        self._load_profile_if_needed()
        self.setWindowTitle("ABET / Program Outcome Mapping")
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._populate_table()

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def _load_profile_if_needed(self):
        if self.profile is not None:
            return
        pid = self.rubric_data.get("profile_id") or \
              self.rubric_data.get("outcome_profile", "")
        try:
            from src.core.outcome_profile import load_profile, load_default_profile
            self.profile = load_profile(pid) if pid else load_default_profile()
        except Exception:
            self.profile = None

    def _program_outcomes(self) -> dict:
        """Return {po_id: description} from profile, or fallback ABET_CS_OUTCOMES."""
        if self.profile:
            return self.profile.program_outcomes
        return ABET_CS_OUTCOMES

    def _lo_ids(self) -> list:
        return sorted(self.profile.course_outcomes.keys()) if self.profile else []

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Header ---
        hdr = QLabel("Map Rubric Criteria to Course Learning Outcomes and Program/ABET Outcomes")
        hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(hdr)

        info = QLabel(
            "Check the boxes for each outcome a criterion assesses. "
            "Use 'Auto-map from title' to apply keyword rules from the loaded profile. "
            "'Save into rubric' embeds the mappings — no separate mapping file needed."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #757575; padding: 4px;")
        layout.addWidget(info)

        # --- Profile selector ---
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Active profile:"))
        self.profile_label = QLabel(
            self.profile.profile_id if self.profile else "None loaded")
        self.profile_label.setStyleSheet("font-weight: bold; color: #3F51B5;")
        prow.addWidget(self.profile_label)
        load_profile_btn = QPushButton("Load Profile…")
        load_profile_btn.clicked.connect(self._load_profile_file)
        prow.addWidget(load_profile_btn)
        prow.addStretch()
        layout.addLayout(prow)

        # --- Tabs: Mapping table | Reference ---
        tabs = QTabWidget()

        # Tab 1: Mapping table
        tab1 = QWidget()
        t1l  = QVBoxLayout(tab1)

        # Button bar
        btn_row = QHBoxLayout()
        for label, slot in [
            ("Auto-map from title",     self._auto_map),
            ("Apply profile defaults",  self._apply_profile_defaults),
            ("Validate mappings",       self._validate),
            ("Clear all mappings",      self._clear_all),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch()
        t1l.addLayout(btn_row)

        # Mapping table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        t1l.addWidget(self.table)

        # File-operation buttons
        file_row = QHBoxLayout()
        for label, slot in [
            ("Save into rubric",  self._save_into_rubric),
            ("Export mapping…",   self._export_mapping),
            ("Import mapping…",   self._import_mapping),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            file_row.addWidget(b)
        file_row.addStretch()
        t1l.addLayout(file_row)

        tabs.addTab(tab1, "Criterion Mapping")

        # Tab 2: Outcome reference
        tab2 = QWidget()
        t2l  = QVBoxLayout(tab2)

        ref_lo = QTextEdit(); ref_lo.setReadOnly(True); ref_lo.setMaximumHeight(160)
        ref_so = QTextEdit(); ref_so.setReadOnly(True); ref_so.setMaximumHeight(160)

        if self.profile:
            ref_lo.setHtml("<b>Course Learning Outcomes:</b><br>" + "<br>".join(
                f"<b>{lo}:</b> {desc}"
                for lo, desc in self.profile.course_outcomes.items()
            ))
            ref_so.setHtml("<b>Program / ABET Outcomes:</b><br>" + "<br>".join(
                f"<b>{po}:</b> {desc}"
                for po, desc in self.profile.program_outcomes.items()
            ))
        else:
            ref_lo.setPlainText("No profile loaded.")
            ref_so.setHtml("<b>ABET CS Outcomes (fallback):</b><br>" + "<br>".join(
                f"<b>{k}:</b> {v}" for k, v in ABET_CS_OUTCOMES.items()
            ))

        t2l.addWidget(QLabel("Course Learning Outcomes"))
        t2l.addWidget(ref_lo)
        t2l.addWidget(QLabel("Program / ABET Outcomes"))
        t2l.addWidget(ref_so)
        tabs.addTab(tab2, "Outcome Reference")

        layout.addWidget(tabs, stretch=1)

        # Dialog buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self):
        criteria = self.rubric_data.get("criteria", [])
        lo_ids   = self._lo_ids()
        po_ids   = sorted(self._program_outcomes().keys())

        # Columns: ID | Title | Points | LOs… | SOs… | Tags | Status
        lo_cols = lo_ids
        so_cols = po_ids
        fixed   = ["ID", "Title", "Points"]
        tag_col = 3 + len(lo_cols) + len(so_cols)
        sta_col = tag_col + 1

        self.table.setColumnCount(sta_col + 1)
        headers = fixed + [f"LO\n{lo}" for lo in lo_cols] + \
                  [f"SO\n{so}" for so in so_cols] + ["Tags", "Status"]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(criteria))

        self._lo_checks: list = []   # [[QCheckBox, ...], ...]
        self._so_checks: list = []
        self._tag_edits: list = []

        for row, crit in enumerate(criteria):
            # ID (read-only)
            id_item = QTableWidgetItem(crit.get("id", ""))
            id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            id_item.setForeground(QColor("#607D8B"))
            self.table.setItem(row, 0, id_item)

            # Title (read-only)
            ti = QTableWidgetItem(crit.get("title", ""))
            ti.setFlags(ti.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, ti)

            # Points (read-only)
            pt = QTableWidgetItem(str(crit.get("points", 0)))
            pt.setFlags(pt.flags() & ~Qt.ItemIsEditable)
            pt.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, pt)

            # LO checkboxes
            lo_row = []
            cur_lo = list(crit.get("course_outcomes", []))
            for col_offset, lo in enumerate(lo_cols):
                cb = self._centered_checkbox(lo in cur_lo)
                self.table.setCellWidget(row, 3 + col_offset, cb)
                lo_row.append((cb, lo))
            self._lo_checks.append(lo_row)

            # SO checkboxes
            so_row = []
            cur_so = list(crit.get("program_outcomes") or crit.get("abet_outcomes") or [])
            for col_offset, so in enumerate(so_cols):
                cb = self._centered_checkbox(so in cur_so)
                self.table.setCellWidget(row, 3 + len(lo_cols) + col_offset, cb)
                so_row.append((cb, so))
            self._so_checks.append(so_row)

            # Tags
            tag_edit = QLineEdit(",".join(crit.get("assessment_tags", [])))
            tag_edit.setPlaceholderText("e.g. runtime, proof")
            self.table.setCellWidget(row, tag_col, tag_edit)
            self._tag_edits.append(tag_edit)

            # Status
            self._update_status(row, cur_lo, cur_so)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for i in range(3, self.table.columnCount() - 2):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(tag_col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(sta_col, QHeaderView.ResizeToContents)

    def _centered_checkbox(self, checked=False) -> QWidget:
        container = QWidget()
        layout    = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(checked)
        layout.addWidget(cb)
        layout.setAlignment(cb, Qt.AlignCenter)
        return container

    def _get_checkbox(self, container) -> QCheckBox:
        return container.findChild(QCheckBox)

    def _update_status(self, row, lo_ids, so_ids):
        lo_col = self.table.columnCount() - 1
        if lo_ids and so_ids:
            txt   = "✓ Mapped"
            color = "#2E7D32"
        elif lo_ids or so_ids:
            txt   = "⚠ Partial"
            color = "#E65100"
        else:
            txt   = "✗ Unmapped"
            color = "#B71C1C"
        item = QTableWidgetItem(txt)
        item.setForeground(QColor(color))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, lo_col, item)

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _auto_map(self):
        if not self.profile:
            QMessageBox.warning(self, "No Profile",
                "Load an outcome profile to use keyword auto-mapping.")
            return
        lo_ids = self._lo_ids()
        so_ids = sorted(self._program_outcomes().keys())
        changed = 0
        for row, crit in enumerate(self.rubric_data.get("criteria", [])):
            title    = crit.get("title", "")
            inf_los  = self.profile.infer_los_from_title(title)
            if inf_los:
                for cb, lo in self._lo_checks[row]:
                    if lo in inf_los:
                        self._get_checkbox(cb).setChecked(True)
                        changed += 1

                inf_pos = self.profile.derive_program_from_los(inf_los)
                for cb, so in self._so_checks[row]:
                    if so in inf_pos:
                        self._get_checkbox(cb).setChecked(True)
        self._refresh_all_status()
        QMessageBox.information(self, "Auto-map Complete",
            f"Applied keyword rules to {len(self.rubric_data.get('criteria',[]))} criteria.\n"
            f"Tip: Review and adjust as needed, then click 'Save into rubric'.")

    def _apply_profile_defaults(self):
        """Map every LO to its default program outcomes from the profile crosswalk."""
        if not self.profile:
            QMessageBox.warning(self, "No Profile", "Load an outcome profile first.")
            return
        for row in range(len(self._lo_checks)):
            # Collect currently checked LOs
            checked_los = [lo for cb, lo in self._lo_checks[row]
                           if self._get_checkbox(cb).isChecked()]
            # Derive SOs
            derived_pos = self.profile.derive_program_from_los(checked_los)
            for cb, so in self._so_checks[row]:
                if so in derived_pos:
                    self._get_checkbox(cb).setChecked(True)
        self._refresh_all_status()

    def _validate(self):
        from src.tools.abet_validation import validate_rubric, issues_summary
        rubric_copy = self._build_updated_rubric()
        lo_ids = list(self.profile.course_outcomes.keys()) if self.profile else None
        so_ids = list(self.profile.program_outcomes.keys()) if self.profile else None
        issues = validate_rubric(rubric_copy, lo_ids, so_ids)
        summary = issues_summary(issues)

        msg = f"Validation result: {summary}\n\n"
        for issue in issues[:30]:
            msg += f"[{issue['level']}] {issue['code']}: {issue['message']}\n"
        if len(issues) > 30:
            msg += f"... and {len(issues)-30} more.\n"

        QMessageBox.information(self, "Validation Results", msg)

    def _clear_all(self):
        reply = QMessageBox.question(self, "Clear All Mappings",
            "This will uncheck all LO and SO boxes. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for row in range(self.table.rowCount()):
            for cb, _ in self._lo_checks[row]:
                self._get_checkbox(cb).setChecked(False)
            for cb, _ in self._so_checks[row]:
                self._get_checkbox(cb).setChecked(False)
        self._refresh_all_status()

    def _save_into_rubric(self):
        """Write LO/SO mappings directly into rubric_data criteria dicts."""
        for row, crit in enumerate(self.rubric_data.get("criteria", [])):
            checked_lo = [lo for cb, lo in self._lo_checks[row]
                          if self._get_checkbox(cb).isChecked()]
            checked_so = [so for cb, so in self._so_checks[row]
                          if self._get_checkbox(cb).isChecked()]
            tags_raw   = self._tag_edits[row].text()
            tags       = [t.strip() for t in tags_raw.split(",") if t.strip()]

            crit["course_outcomes"]  = checked_lo
            crit["program_outcomes"] = checked_so
            crit["abet_outcomes"]    = checked_so   # alias
            crit["assessment_tags"]  = tags

        QMessageBox.information(self, "Saved",
            "Mappings embedded into the rubric in memory.\n\n"
            "To persist them, save the rubric file from the main window\n"
            "('Load Rubric' → the dirty-flag dialog will appear on next load,\n"
            "or use File → Save Rubric if available).")
        self.accept()

    def _export_mapping(self):
        """Export the current mappings to a legacy external JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export ABET Mapping", "abet_mapping.json", "JSON Files (*.json)")
        if not path:
            return
        mappings = {}
        for row, crit in enumerate(self.rubric_data.get("criteria", [])):
            title      = crit.get("title", "")
            checked_so = [so for cb, so in self._so_checks[row]
                          if self._get_checkbox(cb).isChecked()]
            if checked_so:
                w = 1.0
                mappings[title] = {
                    "outcomes": checked_so,
                    "weights":  {so: w for so in checked_so},
                }
        data = {
            "rubric_title":  self.rubric_data.get("title", ""),
            "profile_id":    self.profile.profile_id if self.profile else "",
            "mappings":      mappings,
            "created_date":  datetime.now().isoformat(),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        QMessageBox.information(self, "Exported",
            f"Mapping file saved to:\n{path}")

    def _import_mapping(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import ABET Mapping", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load mapping: {e}")
            return

        # Support both new embedded format (criteria with outcomes) and
        # legacy mappings-dict format
        title_to_so: dict = {}
        if "mappings" in data:
            for title, md in data["mappings"].items():
                title_to_so[title] = md.get("outcomes", [])
        elif "criteria" in data:
            for crit in data["criteria"]:
                t  = crit.get("title","")
                so = list(crit.get("program_outcomes") or crit.get("abet_outcomes") or [])
                if t and so:
                    title_to_so[t] = so

        for row, crit in enumerate(self.rubric_data.get("criteria", [])):
            title = crit.get("title","")
            if title in title_to_so:
                sos = title_to_so[title]
                for cb, so in self._so_checks[row]:
                    self._get_checkbox(cb).setChecked(so in sos)

        self._refresh_all_status()
        QMessageBox.information(self, "Imported",
            "Mappings loaded from file. Review and click 'Save into rubric'.")

    def _load_profile_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Outcome Profile", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            from src.core.outcome_profile import load_profile
            self.profile = load_profile(path)
            self.profile_label.setText(self.profile.profile_id)
            # Rebuild the mapping table immediately so new LO/SO columns appear
            self._rebuild_table()
            QMessageBox.information(self, "Profile Loaded",
                f"Profile '{self.profile.profile_id}' loaded and table rebuilt.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load profile: {e}")

    def _rebuild_table(self):
        """Rebuild the mapping table after a profile change, preserving existing checks."""
        # Save currently checked LOs/SOs per row index before clearing
        saved_lo: Dict[int, List[str]] = {}
        saved_so: Dict[int, List[str]] = {}
        saved_tags: Dict[int, str] = {}
        for row in range(min(len(self._lo_checks), self.table.rowCount())):
            saved_lo[row]   = [lo for cb, lo in self._lo_checks[row]
                               if self._get_checkbox(cb).isChecked()]
            saved_so[row]   = [so for cb, so in self._so_checks[row]
                               if self._get_checkbox(cb).isChecked()]
            saved_tags[row] = self._tag_edits[row].text() if row < len(self._tag_edits) else ""

        # Clear and repopulate
        self.table.clearContents()
        self.table.setRowCount(0)
        self._lo_checks = []
        self._so_checks = []
        self._tag_edits = []
        self._populate_table()

        # Restore saved checks (matching by position, new columns may differ)
        for row in range(self.table.rowCount()):
            if row in saved_lo:
                for cb, lo in self._lo_checks[row]:
                    if lo in saved_lo[row]:
                        self._get_checkbox(cb).setChecked(True)
            if row in saved_so:
                for cb, so in self._so_checks[row]:
                    if so in saved_so[row]:
                        self._get_checkbox(cb).setChecked(True)
            if row in saved_tags and row < len(self._tag_edits):
                self._tag_edits[row].setText(saved_tags[row])
        self._refresh_all_status()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_all_status(self):
        for row in range(self.table.rowCount()):
            lo = [lo for cb, lo in self._lo_checks[row]
                  if self._get_checkbox(cb).isChecked()]
            so = [so for cb, so in self._so_checks[row]
                  if self._get_checkbox(cb).isChecked()]
            self._update_status(row, lo, so)

    def _build_updated_rubric(self) -> dict:
        import copy
        rubric = copy.deepcopy(self.rubric_data)
        for row, crit in enumerate(rubric.get("criteria", [])):
            crit["course_outcomes"]  = [lo for cb, lo in self._lo_checks[row]
                                         if self._get_checkbox(cb).isChecked()]
            crit["program_outcomes"] = [so for cb, so in self._so_checks[row]
                                         if self._get_checkbox(cb).isChecked()]
            crit["abet_outcomes"]    = crit["program_outcomes"]
        return rubric

    def get_updated_rubric_data(self) -> dict:
        """Call after dialog.exec_() == Accepted to get rubric with mappings."""
        return self._build_updated_rubric()


# ===========================================================================
# ABETReportDialog  (Phase 4 full version)
# ===========================================================================

class ABETReportDialog(QDialog):
    """
    Assignment-level ABET/program-outcome report generator.

    Features:
    - Mapping file is optional (new rubrics embed outcomes)
    - Profile selection
    - Evidence policy selector
    - Runs validation and shows summary before generating
    - Exports JSON + CSV + XLSX
    """

    def __init__(self, parent=None, rubric_data: dict = None):
        super().__init__(parent)
        self.rubric_data    = rubric_data or {}
        self.selected_dir   = None
        self.selected_mapping = None
        self.setWindowTitle("Generate ABET Assessment Report")
        self.setMinimumSize(720, 580)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hdr = QLabel("ABET / Program Outcome Report Generator")
        hdr.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(hdr)

        note = QLabel(
            "Grade students normally, then generate a report here. "
            "If your rubric has embedded outcomes, no separate mapping file is needed."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #757575; padding: 4px;")
        layout.addWidget(note)

        tabs = QTabWidget()

        # --- Tab 1: Settings ---
        t1 = QWidget(); t1l = QVBoxLayout(t1)

        # Course info
        ci_grp = QGroupBox("Course Information")
        ci_lay = QVBoxLayout()
        self.course_code   = self._field_row(ci_lay, "Course Code:", "e.g. CS 2500")
        self.course_name   = self._field_row(ci_lay, "Course Name:", "e.g. Algorithms")
        self.semester_edit = self._field_row(ci_lay, "Semester:", "e.g. Fall 2026")
        self.assessment_name = self._field_row(ci_lay, "Assessment Name:", "e.g. Midterm 1")
        self.target_pct    = self._field_row(ci_lay, "Target % (passing+):", "75")
        ci_grp.setLayout(ci_lay)
        t1l.addWidget(ci_grp)

        # Assessment directory
        dir_grp = QGroupBox("Assessment Data")
        dir_lay = QVBoxLayout()
        d_row = QHBoxLayout()
        self.dir_label = QLabel("No directory selected")
        self.dir_label.setStyleSheet("color: #757575; font-style: italic;")
        d_row.addWidget(self.dir_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._select_dir)
        d_row.addWidget(browse_btn)
        dir_lay.addLayout(d_row)
        dir_grp.setLayout(dir_lay)
        t1l.addWidget(dir_grp)

        # Mapping file (optional)
        map_grp = QGroupBox("ABET Mapping File (optional — not needed for embedded-outcome rubrics)")
        map_lay = QVBoxLayout()
        m_row = QHBoxLayout()
        self.mapping_label = QLabel("None selected (will use embedded outcomes)")
        self.mapping_label.setStyleSheet("color: #757575; font-style: italic;")
        m_row.addWidget(self.mapping_label, 1)
        map_btn = QPushButton("Browse…")
        map_btn.clicked.connect(self._select_mapping)
        m_row.addWidget(map_btn)
        clr_btn = QPushButton("Clear")
        clr_btn.clicked.connect(self._clear_mapping)
        m_row.addWidget(clr_btn)
        map_lay.addLayout(m_row)
        map_grp.setLayout(map_lay)
        t1l.addWidget(map_grp)

        # Profile
        prof_grp = QGroupBox("Outcome Profile")
        prof_lay = QHBoxLayout()
        from src.core.outcome_profile import list_available_profiles
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("(default — cs2500_algorithms)")
        for pid in list_available_profiles():
            self.profile_combo.addItem(pid)
        prof_lay.addWidget(QLabel("Profile:"))
        prof_lay.addWidget(self.profile_combo, 1)
        load_prof_btn = QPushButton("Load from file…")
        load_prof_btn.clicked.connect(self._load_profile)
        prof_lay.addWidget(load_prof_btn)
        prof_grp.setLayout(prof_lay)
        t1l.addWidget(prof_grp)

        # Evidence policy
        pol_grp = QGroupBox("Evidence Policy")
        pol_lay = QHBoxLayout()
        self.policy_combo = QComboBox()
        self.policy_combo.addItems([
            "counted_only (default — best-N-of-M safe)",
            "selected_only",
            "all",
        ])
        pol_lay.addWidget(QLabel("Include:"))
        pol_lay.addWidget(self.policy_combo, 1)
        pol_grp.setLayout(pol_lay)
        t1l.addWidget(pol_grp)

        t1l.addStretch()
        tabs.addTab(t1, "Settings")

        # --- Tab 2: Validation ---
        t2 = QWidget(); t2l = QVBoxLayout(t2)
        self.validation_display = QTextEdit()
        self.validation_display.setReadOnly(True)
        self.validation_display.setPlaceholderText(
            "Click 'Run Validation' to check mappings before generating a report.")
        t2l.addWidget(self.validation_display)
        val_btn = QPushButton("Run Validation")
        val_btn.clicked.connect(self._run_validation)
        t2l.addWidget(val_btn)
        tabs.addTab(t2, "Validation")

        layout.addWidget(tabs, stretch=1)

        # Generate button
        gen_btn = QPushButton("Generate ABET Report")
        gen_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 10px; font-size: 13px; }"
            "QPushButton:hover { background-color: #388E3C; }")
        gen_btn.clicked.connect(self._generate)
        layout.addWidget(gen_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _field_row(self, parent_layout, label: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        row.addWidget(lbl)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        row.addWidget(edit)
        parent_layout.addLayout(row)
        return edit

    # ------------------------------------------------------------------
    # Button slots
    # ------------------------------------------------------------------

    def _select_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Assessment Directory")
        if d:
            self.selected_dir = d
            self.dir_label.setText(os.path.basename(d))
            self.dir_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

    def _select_mapping(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ABET Mapping", "", "JSON Files (*.json)")
        if path:
            self.selected_mapping = path
            self.mapping_label.setText(os.path.basename(path))
            self.mapping_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

    def _clear_mapping(self):
        self.selected_mapping = None
        self.mapping_label.setText("None selected (will use embedded outcomes)")
        self.mapping_label.setStyleSheet("color: #757575; font-style: italic;")

    def _load_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Outcome Profile", "", "JSON Files (*.json)")
        if path:
            self.profile_combo.setCurrentText(path)

    def _get_profile(self):
        text = self.profile_combo.currentText()
        try:
            from src.core.outcome_profile import load_profile, load_default_profile
            if text.startswith("(default") or not text:
                return load_default_profile()
            return load_profile(text)
        except Exception:
            return None

    def _get_policy(self) -> str:
        return self.policy_combo.currentText().split()[0]

    def _run_validation(self):
        if not self.selected_dir:
            self.validation_display.setPlainText("Please select an assessment directory first.")
            return

        profile = self._get_profile()
        lo_ids  = list(profile.course_outcomes.keys()) if profile else None
        so_ids  = list(profile.program_outcomes.keys()) if profile else None

        from src.tools.abet_validation import validate_all, issues_summary
        import glob

        assessments = []
        for path in glob.glob(os.path.join(self.selected_dir, "*.json")):
            try:
                with open(path) as fh:
                    data = json.load(fh)
                if "criteria" in data:
                    assessments.append(data)
            except Exception:
                pass

        rubric = self.rubric_data if self.rubric_data.get("criteria") else {"criteria": []}
        issues = validate_all(rubric, assessments, lo_ids, so_ids,
                              policy=self._get_policy())
        summary = issues_summary(issues)

        lines = [f"=== Validation: {summary} ===\n"]
        for iss in issues:
            lines.append(f"[{iss['level']}] {iss['code']}: {iss['message']}")
        if not issues:
            lines.append("No issues found — report is ready to generate.")
        self.validation_display.setPlainText("\n".join(lines))

    def _generate(self):
        if not self.selected_dir:
            QMessageBox.warning(self, "Missing Information",
                                "Please select an assessment directory.")
            return
        if not self.course_code.text() or not self.assessment_name.text():
            QMessageBox.warning(self, "Missing Information",
                                "Please fill in course code and assessment name.")
            return
        try:
            target = float(self.target_pct.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "Target percentage must be a number.")
            return

        try:
            from src.tools.abet_tool import ABETAssessmentAnalyzer, create_mapping_from_dict
            from src.tools.abet_export import export_assignment_report

            profile = self._get_profile()

            mapping = None
            if self.selected_mapping:
                with open(self.selected_mapping, "r") as fh:
                    mapping_data = json.load(fh)
                mapping = create_mapping_from_dict(mapping_data)

            analyzer = ABETAssessmentAnalyzer(mapping, outcome_profile=profile)

            prog = QProgressDialog("Loading assessments…", None, 0, 0, self)
            prog.setWindowModality(Qt.WindowModal); prog.show()
            count = analyzer.load_assessments_from_directory(self.selected_dir)
            prog.close()

            if count == 0:
                QMessageBox.warning(self, "No Assessments Found",
                    "No valid assessment files found in the selected directory.")
                return

            course_info = {
                "course_code":       self.course_code.text(),
                "course_name":       self.course_name.text(),
                "semester":          self.semester_edit.text(),
                "assessment":        self.assessment_name.text(),
                "target_percentage": target,
            }

            safe_c = "".join(c if c.isalnum() else "_" for c in self.course_code.text())
            safe_a = "".join(c if c.isalnum() else "_" for c in self.assessment_name.text())

            out_dir, _ = QFileDialog.getSaveFileName(
                self, "Save Report to Folder", f"abet_{safe_c}_{safe_a}",
                "JSON Report (*.json)")
            if not out_dir:
                return

            # Derive output directory from chosen path
            export_dir = os.path.splitext(out_dir)[0] + "_report"
            os.makedirs(export_dir, exist_ok=True)
            report_json = os.path.join(export_dir, "abet_report.json")

            prog2 = QProgressDialog("Generating report…", None, 0, 0, self)
            prog2.setWindowModality(Qt.WindowModal); prog2.show()
            report = analyzer.generate_abet_report(
                report_json, course_info, policy=self._get_policy())
            files = export_assignment_report(report, export_dir)
            prog2.close()

            results_dlg = ABETResultsDialog(report, report_json, self)
            results_dlg.exec_()

            QMessageBox.information(self, "Export Complete",
                f"Report saved to:\n{export_dir}\n\n"
                f"Files: {len(files)} exported.")

        except Exception as exc:
            QMessageBox.critical(self, "Error",
                f"Failed to generate report:\n{exc}")


# ===========================================================================
# ABETResultsDialog
# ===========================================================================

class ABETResultsDialog(QDialog):
    """Display ABET report results with colour-coded summary tables."""

    def __init__(self, report: dict, report_path: str, parent=None):
        super().__init__(parent)
        self.report      = report
        self.report_path = report_path
        self.setWindowTitle("ABET Assessment Report — Results")
        self.setMinimumSize(860, 640)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hdr = QLabel("ABET Assessment Report — Results")
        hdr.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(hdr)

        ci = self.report.get("course_info", {})
        info_text = (
            f"{ci.get('course_code','')} — {ci.get('course_name','')}\n"
            f"{ci.get('assessment','')} ({ci.get('semester','')})\n"
            f"Students assessed: {self.report.get('num_students',0)}  |  "
            f"Profile: {self.report.get('profile_id','—')}"
        )
        info_lbl = QLabel(info_text)
        info_lbl.setStyleSheet(
            "color: #555; padding: 8px; background: #F5F5F5; border-radius: 4px;")
        layout.addWidget(info_lbl)

        tabs = QTabWidget()

        # --- Program Outcomes table ---
        so_tab = QWidget(); so_lay = QVBoxLayout(so_tab)
        so_lay.addWidget(self._build_outcome_table("program_outcomes"))
        tabs.addTab(so_tab, "Program / ABET Outcomes")

        # --- Course LO table ---
        lo_tab = QWidget(); lo_lay = QVBoxLayout(lo_tab)
        lo_lay.addWidget(self._build_outcome_table("course_outcomes"))
        tabs.addTab(lo_tab, "Course LO Outcomes")

        # --- Summary text ---
        sum_tab = QWidget(); sum_lay = QVBoxLayout(sum_tab)
        txt = QTextEdit(); txt.setReadOnly(True)
        txt.setPlainText(self.report.get("summary", ""))
        txt.setStyleSheet("font-family: 'Courier New', monospace; font-size: 11px;")
        sum_lay.addWidget(txt)
        tabs.addTab(sum_tab, "Detailed Summary")

        layout.addWidget(tabs, stretch=1)

        saved_lbl = QLabel(f"Report JSON: {self.report_path}")
        saved_lbl.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 4px;")
        layout.addWidget(saved_lbl)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _build_outcome_table(self, key: str) -> QTableWidget:
        data    = self.report.get("outcome_summary", {}).get(key, {})
        target  = float(self.report.get("course_info", {}).get("target_percentage", 75.0))
        descs   = self.report.get("outcome_descriptions", {}).get(key, {})

        tbl = QTableWidget()
        tbl.setColumnCount(6)
        tbl.setHorizontalHeaderLabels(
            ["Outcome", "Mean", "Adequate+", "Target", "Meets?", "Bands"])
        tbl.setRowCount(len(data))

        for row, oid in enumerate(sorted(data.keys())):
            d        = data[oid]
            adeq_pct = d.get("proficient_plus_pct", 0.0)
            meets    = d.get("meets_target", adeq_pct >= target)
            bands    = d.get("band_counts", {})

            # Outcome ID + tooltip for description
            oid_item = QTableWidgetItem(oid)
            oid_item.setFont(QFont("", -1, QFont.Bold))
            oid_item.setToolTip(descs.get(oid, ""))
            tbl.setItem(row, 0, oid_item)

            tbl.setItem(row, 1, QTableWidgetItem(f"{d.get('mean',0):.1f}%"))

            adeq_item = QTableWidgetItem(f"{adeq_pct:.1f}%")
            if adeq_pct >= target:
                adeq_item.setBackground(QColor("#C8E6C9"))
            elif adeq_pct >= target * 0.9:
                adeq_item.setBackground(QColor("#FFF9C4"))
            else:
                adeq_item.setBackground(QColor("#FFCDD2"))
            tbl.setItem(row, 2, adeq_item)

            tbl.setItem(row, 3, QTableWidgetItem(f"{target:.0f}%"))

            meets_item = QTableWidgetItem("✓ Yes" if meets else "✗ No")
            meets_item.setFont(QFont("", -1, QFont.Bold))
            meets_item.setForeground(QColor("#2E7D32" if meets else "#B71C1C"))
            tbl.setItem(row, 4, meets_item)

            # Band distribution summary
            band_parts = []
            for bname, bdata in bands.items():
                if bname in ("adequate_or_higher","proficient_or_higher"):
                    continue
                band_parts.append(f"{bname[0].upper()}:{bdata.get('count',0)}")
            tbl.setItem(row, 5, QTableWidgetItem("  ".join(band_parts)))

        header = tbl.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        return tbl


# ===========================================================================
# SemesterABETReportDialog  (Phase 3+4 new dialog)
# ===========================================================================

class SemesterABETReportDialog(QDialog):
    """
    Semester-level ABET aggregation dialog.

    Supports:
    - Config JSON file mode
    - Folder-scan mode
    - Profile selection
    - Evidence policy
    - Progress display
    - Result tables: Outcome Summary | By Assessment | Coverage Matrix | Notes
    - Export to XLSX / CSV
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Semester ABET Report")
        self.setMinimumSize(860, 660)
        self._report = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hdr = QLabel("Semester-Level ABET Report Generator")
        hdr.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(hdr)

        note = QLabel(
            "Aggregate ABET outcomes across multiple assignments for the full semester. "
            "Either load a semester config file or scan a semester folder."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #757575; padding: 4px;")
        layout.addWidget(note)

        tabs = QTabWidget()
        self._tabs = tabs

        # --- Settings tab ---
        st = QWidget(); stl = QVBoxLayout(st)

        # Input source
        src_grp = QGroupBox("Data Source")
        src_lay = QVBoxLayout()

        # Config file
        cfg_row = QHBoxLayout()
        self.config_label = QLabel("No config file selected")
        self.config_label.setStyleSheet("color: #757575; font-style: italic;")
        cfg_btn = QPushButton("Load semester config…")
        cfg_btn.clicked.connect(self._load_config)
        cfg_row.addWidget(QLabel("Config JSON:"))
        cfg_row.addWidget(self.config_label, 1)
        cfg_row.addWidget(cfg_btn)
        src_lay.addLayout(cfg_row)

        # Or folder
        fld_row = QHBoxLayout()
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setStyleSheet("color: #757575; font-style: italic;")
        fld_btn = QPushButton("Scan semester folder…")
        fld_btn.clicked.connect(self._load_folder)
        fld_row.addWidget(QLabel("Folder:"))
        fld_row.addWidget(self.folder_label, 1)
        fld_row.addWidget(fld_btn)
        src_lay.addLayout(fld_row)

        src_grp.setLayout(src_lay)
        stl.addWidget(src_grp)

        # Course info overrides
        ci_grp = QGroupBox("Course Info (overrides config file values if filled)")
        ci_lay = QVBoxLayout()
        self.sem_course_code  = self._field_row(ci_lay, "Course Code:", "CS 2500")
        self.sem_course_name  = self._field_row(ci_lay, "Course Name:", "Algorithms")
        self.sem_semester     = self._field_row(ci_lay, "Semester:", "Fall 2026")
        self.sem_instructor   = self._field_row(ci_lay, "Instructor:", "")
        self.sem_target       = self._field_row(ci_lay, "Target %:", "75")
        ci_grp.setLayout(ci_lay)
        stl.addWidget(ci_grp)

        # Profile
        prof_grp = QGroupBox("Outcome Profile")
        prof_lay = QHBoxLayout()
        from src.core.outcome_profile import list_available_profiles
        self.sem_profile_combo = QComboBox()
        self.sem_profile_combo.addItem("(from config / default)")
        for pid in list_available_profiles():
            self.sem_profile_combo.addItem(pid)
        prof_lay.addWidget(QLabel("Profile:"))
        prof_lay.addWidget(self.sem_profile_combo, 1)
        prof_grp.setLayout(prof_lay)
        stl.addWidget(prof_grp)

        # Policy
        pol_grp = QGroupBox("Evidence Policy")
        pol_lay = QHBoxLayout()
        self.sem_policy = QComboBox()
        self.sem_policy.addItems(["counted_only (default)", "selected_only", "all"])
        pol_lay.addWidget(QLabel("Include:"))
        pol_lay.addWidget(self.sem_policy, 1)
        pol_grp.setLayout(pol_lay)
        stl.addWidget(pol_grp)

        stl.addStretch()
        tabs.addTab(st, "Settings")

        # --- Results tab (populated after generation) ---
        self.results_tabs = QTabWidget()
        tabs.addTab(self.results_tabs, "Results")

        layout.addWidget(tabs, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        gen_btn = QPushButton("Generate Semester Report")
        gen_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 10px; font-size: 13px; }"
            "QPushButton:hover { background-color: #388E3C; }")
        gen_btn.clicked.connect(self._generate)
        btn_row.addWidget(gen_btn)

        export_btn = QPushButton("Export XLSX / CSV…")
        export_btn.clicked.connect(self._export)
        btn_row.addWidget(export_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._config_obj  = None   # SemesterABETReport instance
        self._folder_path = None

    def _field_row(self, parent_layout, label: str, placeholder: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label); lbl.setFixedWidth(110)
        row.addWidget(lbl)
        edit = QLineEdit(); edit.setPlaceholderText(placeholder)
        row.addWidget(edit)
        parent_layout.addLayout(row)
        return edit

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Semester Config", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            from src.tools.semester_abet_report import SemesterABETReport
            self._config_obj  = SemesterABETReport.from_config(path,
                                    profile=self._get_profile())
            self._folder_path = None
            self.config_label.setText(os.path.basename(path))
            self.config_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.folder_label.setText("(using config file)")
            self.folder_label.setStyleSheet("color: #757575; font-style: italic;")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to load config: {exc}")

    def _load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Semester Folder")
        if not folder:
            return
        try:
            from src.tools.semester_abet_report import SemesterABETReport
            self._folder_path = folder
            self._config_obj  = SemesterABETReport.from_folder(
                folder, profile=self._get_profile())
            self.folder_label.setText(os.path.basename(folder))
            self.folder_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.config_label.setText("(using folder scan)")
            self.config_label.setStyleSheet("color: #757575; font-style: italic;")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to scan folder: {exc}")

    def _get_profile(self):
        text = self.sem_profile_combo.currentText()
        if text.startswith("("):
            return None
        try:
            from src.core.outcome_profile import load_profile
            return load_profile(text)
        except Exception:
            return None

    def _get_policy(self) -> str:
        return self.sem_policy.currentText().split()[0]

    def _apply_overrides(self):
        if self._config_obj is None:
            return
        for field, widget in [
            ("course_code",  self.sem_course_code),
            ("course_name",  self.sem_course_name),
            ("semester",     self.sem_semester),
            ("instructor",   self.sem_instructor),
        ]:
            val = widget.text().strip()
            if val:
                self._config_obj.course_info[field] = val
        try:
            target = float(self.sem_target.text())
            self._config_obj.course_info["target_percentage"] = target
        except ValueError:
            pass

        profile = self._get_profile()
        if profile:
            self._config_obj.profile = profile

    def _generate(self):
        if self._config_obj is None:
            QMessageBox.warning(self, "No Data Source",
                "Please load a semester config file or scan a folder first.")
            return

        self._apply_overrides()

        prog = QProgressDialog("Aggregating semester data…", None, 0, 0, self)
        prog.setWindowModality(Qt.WindowModal); prog.show()
        try:
            report = self._config_obj.aggregate(policy=self._get_policy())
            self._report = report
            prog.close()
            self._populate_results(report)
            self._tabs.setCurrentIndex(1)  # switch to Results tab
        except Exception as exc:
            prog.close()
            QMessageBox.critical(self, "Error", f"Aggregation failed:\n{exc}")

    def _populate_results(self, report: dict):
        """Fill Results tab with summary tables."""
        self.results_tabs.clear()

        summary     = report.get("semester_summary", {})
        po_data     = summary.get("program_outcomes", {})
        lo_data     = summary.get("course_outcomes", {})
        target      = float(report.get("course_info",{}).get("target_percentage",75))
        po_desc     = report.get("outcome_descriptions",{}).get("program_outcomes",{})
        lo_desc     = report.get("outcome_descriptions",{}).get("course_outcomes",{})
        details     = report.get("assignment_details", [])
        asmnt_names = [a.get("assessment_name", a.get("assessment_id",""))
                       for a in details if "error" not in a]

        # --- Tab A: Overall Outcome Summary ---
        tA = QWidget(); tlA = QVBoxLayout(tA)
        so_tbl = self._build_summary_table(po_data, po_desc, target, "Program Outcome")
        tlA.addWidget(so_tbl)
        self.results_tabs.addTab(tA, "Program Outcomes")

        # --- Tab B: Outcome by Assessment ---
        tB = QWidget(); tlB = QVBoxLayout(tB)
        by_so = summary.get("by_assessment_so", {})
        all_sos = sorted(by_so.keys())
        by_tbl = QTableWidget(len(all_sos), len(asmnt_names) + 2)
        by_tbl.setHorizontalHeaderLabels(["Outcome"] + asmnt_names + ["Overall"])
        for r, oid in enumerate(all_sos):
            by_tbl.setItem(r, 0, QTableWidgetItem(oid))
            per = by_so.get(oid, {})
            for c, name in enumerate(asmnt_names):
                val = per.get(name)
                cell = QTableWidgetItem(f"{val:.1f}%" if val is not None else "—")
                by_tbl.setItem(r, c+1, cell)
            overall = po_data.get(oid,{}).get("mean")
            by_tbl.setItem(r, len(asmnt_names)+1,
                           QTableWidgetItem(f"{overall:.1f}%" if overall else "—"))
        by_tbl.horizontalHeader().setStretchLastSection(True)
        tlB.addWidget(by_tbl)
        self.results_tabs.addTab(tB, "By Assessment")

        # --- Tab C: Evidence Coverage Matrix ---
        tC = QWidget(); tlC = QVBoxLayout(tC)
        coverage = summary.get("coverage_matrix", {})
        all_los  = summary.get("all_lo_ids", [])
        cov_tbl  = QTableWidget(len(coverage), len(all_los) + 1)
        cov_tbl.setHorizontalHeaderLabels(["Assessment"] + all_los)
        for r, (aname, lo_map) in enumerate(sorted(coverage.items())):
            cov_tbl.setItem(r, 0, QTableWidgetItem(aname))
            for c, lo in enumerate(all_los):
                yes = lo_map.get(lo, False)
                cell = QTableWidgetItem("Yes" if yes else "No")
                cell.setBackground(QColor("#C8E6C9") if yes else QColor("#FFCDD2"))
                cov_tbl.setItem(r, c+1, cell)
        cov_tbl.horizontalHeader().setStretchLastSection(True)
        tlC.addWidget(cov_tbl)
        self.results_tabs.addTab(tC, "Coverage Matrix")

        # --- Tab D: LO Summary ---
        tD = QWidget(); tlD = QVBoxLayout(tD)
        lo_tbl = self._build_summary_table(lo_data, lo_desc, target, "Course LO")
        tlD.addWidget(lo_tbl)
        self.results_tabs.addTab(tD, "Course LOs")

        # --- Tab E: Closing the Loop ---
        tE = QWidget(); tlE = QVBoxLayout(tE)
        ctl = report.get("closing_the_loop", {})
        for label, key in [
            ("Reflection:", "reflection"),
            ("Planned Improvements:", "planned_improvements"),
            ("Notes for Next Offering:", "notes_for_next_offering"),
        ]:
            tlE.addWidget(QLabel(label))
            te = QTextEdit(ctl.get(key, ""))
            te.setMaximumHeight(100)
            tlE.addWidget(te)
        self.results_tabs.addTab(tE, "Closing the Loop")

    def _build_summary_table(self, data: dict, descs: dict,
                              target: float, row_label: str) -> QTableWidget:
        tbl = QTableWidget(len(data), 6)
        tbl.setHorizontalHeaderLabels(
            [row_label, "Mean", "Adequate+", "Target", "Meets?", "N"])
        for r, oid in enumerate(sorted(data.keys())):
            d        = data[oid]
            adeq_pct = d.get("proficient_plus_pct", 0.0)
            meets    = d.get("meets_target", adeq_pct >= target)

            oid_item = QTableWidgetItem(oid)
            oid_item.setFont(QFont("", -1, QFont.Bold))
            oid_item.setToolTip(descs.get(oid, ""))
            tbl.setItem(r, 0, oid_item)

            tbl.setItem(r, 1, QTableWidgetItem(f"{d.get('mean',0):.1f}%"))

            ap = QTableWidgetItem(f"{adeq_pct:.1f}%")
            ap.setBackground(QColor("#C8E6C9" if meets else "#FFCDD2"))
            tbl.setItem(r, 2, ap)

            tbl.setItem(r, 3, QTableWidgetItem(f"{target:.0f}%"))

            mi = QTableWidgetItem("✓ Yes" if meets else "✗ No")
            mi.setFont(QFont("", -1, QFont.Bold))
            mi.setForeground(QColor("#2E7D32" if meets else "#B71C1C"))
            tbl.setItem(r, 4, mi)

            tbl.setItem(r, 5, QTableWidgetItem(str(d.get("count",0))))

        tbl.horizontalHeader().setStretchLastSection(True)
        return tbl

    def _export(self):
        if self._report is None:
            QMessageBox.warning(self, "No Report",
                "Generate the semester report first.")
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Select Export Folder")
        if not folder:
            return
        try:
            from src.tools.abet_export import export_semester_report
            files = export_semester_report(self._report, folder)
            QMessageBox.information(self, "Export Complete",
                f"Exported {len(files)} file(s) to:\n{folder}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
