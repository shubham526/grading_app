"""
ABET Dialog UI Components

Save this as: src/ui/dialogs/abet_dialogs.py
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QCheckBox, QTextEdit,
    QGroupBox, QDialogButtonBox, QFileDialog, QMessageBox,
    QLineEdit, QHeaderView, QProgressDialog, QWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import json
import os
from datetime import datetime

# ABET Student Outcomes for Computer Science (2025-2026 Criteria)
ABET_CS_OUTCOMES = {
    "SO1": "Analyze a complex computing problem and to apply principles of computing and other relevant disciplines to identify solutions",
    "SO2": "Design, implement, and evaluate a computing-based solution to meet a given set of computing requirements in the context of the problem's discipline",
    "SO3": "Communicate effectively in a variety of professional contexts",
    "SO4": "Recognize professional responsibilities and make informed judgments in computing practice based on legal and ethical principles",
    "SO5": "Function effectively as a member or leader of a team engaged in activities appropriate to the program's discipline",
    "SO6": "Apply computer science theory and software development fundamentals to produce computing-based solutions"
}


class ABETMappingDialog(QDialog):
    """Dialog for creating and editing ABET outcome mappings."""

    def __init__(self, rubric_data, parent=None):
        super().__init__(parent)
        self.rubric_data = rubric_data
        self.mappings = {}
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("ABET Outcome Mapping")
        self.setMinimumSize(1000, 700)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Map Rubric Criteria to ABET Student Outcomes")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(header)

        # Instructions
        instructions = QLabel(
            "Select which ABET outcomes each criterion assesses. "
            "Check the boxes for outcomes, and the tool will automatically calculate "
            "ABET performance data when you generate reports."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #757575; margin-bottom: 10px; padding: 5px;")
        layout.addWidget(instructions)

        # File operations
        file_layout = QHBoxLayout()

        load_btn = QPushButton("Load Mapping")
        load_btn.clicked.connect(self.load_mapping)
        file_layout.addWidget(load_btn)

        save_btn = QPushButton("Save Mapping")
        save_btn.clicked.connect(self.save_mapping)
        file_layout.addWidget(save_btn)

        file_layout.addStretch()
        layout.addLayout(file_layout)

        # Mapping table
        self.create_mapping_table()
        layout.addWidget(self.table)

        # ABET Outcomes reference
        ref_group = QGroupBox("ABET Student Outcomes Reference (CS 2025-2026)")
        ref_layout = QVBoxLayout()

        ref_text = QTextEdit()
        ref_text.setReadOnly(True)
        ref_text.setMaximumHeight(180)

        reference = []
        for outcome_id, description in ABET_CS_OUTCOMES.items():
            reference.append(f"<b>{outcome_id}:</b> {description}")

        ref_text.setHtml("<br><br>".join(reference))
        ref_layout.addWidget(ref_text)
        ref_group.setLayout(ref_layout)
        layout.addWidget(ref_group)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def create_mapping_table(self):
        """Create the mapping table."""
        self.table = QTableWidget()

        # Set up columns: Criterion + one column per ABET outcome
        num_outcomes = len(ABET_CS_OUTCOMES)
        self.table.setColumnCount(1 + num_outcomes)

        headers = ["Criterion"] + list(ABET_CS_OUTCOMES.keys())
        self.table.setHorizontalHeaderLabels(headers)

        # Set up rows: one per criterion
        criteria = self.rubric_data.get('criteria', [])
        self.table.setRowCount(len(criteria))

        # Populate table
        for row, criterion in enumerate(criteria):
            # Criterion title
            title_item = QTableWidgetItem(criterion['title'])
            title_item.setFlags(title_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, title_item)

            # Checkboxes for each outcome
            for col, outcome_id in enumerate(ABET_CS_OUTCOMES.keys(), start=1):
                checkbox = QCheckBox()
                checkbox.setStyleSheet("margin-left: 50%; margin-right: 50%;")

                # Center the checkbox
                widget_container = QWidget()
                checkbox_layout = QHBoxLayout(widget_container)
                checkbox_layout.addWidget(checkbox)
                checkbox_layout.setAlignment(Qt.AlignCenter)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)

                self.table.setCellWidget(row, col, widget_container)

        # Adjust column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

    def get_mappings(self):
        """Extract mappings from the table."""
        mappings = {}
        criteria = self.rubric_data.get('criteria', [])

        for row in range(self.table.rowCount()):
            criterion = criteria[row]
            title = criterion['title']

            outcome_ids = []
            for col, outcome_id in enumerate(ABET_CS_OUTCOMES.keys(), start=1):
                widget = self.table.cellWidget(row, col)
                if widget:
                    checkbox = widget.findChild(QCheckBox)
                    if checkbox and checkbox.isChecked():
                        outcome_ids.append(outcome_id)

            if outcome_ids:
                # Create equal weights by default
                equal_weight = 1.0 / len(outcome_ids)
                weights = {oid: equal_weight for oid in outcome_ids}

                mappings[title] = {
                    'outcomes': outcome_ids,
                    'weights': weights
                }

        return mappings

    def set_mappings(self, mappings):
        """Set the mappings in the table."""
        criteria = self.rubric_data.get('criteria', [])

        for row in range(self.table.rowCount()):
            criterion = criteria[row]
            title = criterion['title']

            if title in mappings:
                mapping_data = mappings[title]
                outcome_ids = mapping_data.get('outcomes', [])

                for col, outcome_id in enumerate(ABET_CS_OUTCOMES.keys(), start=1):
                    if outcome_id in outcome_ids:
                        widget = self.table.cellWidget(row, col)
                        if widget:
                            checkbox = widget.findChild(QCheckBox)
                            if checkbox:
                                checkbox.setChecked(True)

    def save_mapping(self):
        """Save the mapping to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save ABET Mapping",
            "abet_mapping.json",
            "JSON Files (*.json)"
        )

        if not file_path:
            return

        mappings = self.get_mappings()

        data = {
            "rubric_title": self.rubric_data.get('title', 'Unknown'),
            "mappings": mappings,
            "created_date": datetime.now().isoformat()
        }

        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)

            QMessageBox.information(
                self,
                "Success",
                f"ABET mapping saved successfully to:\n{file_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save mapping: {str(e)}"
            )

    def load_mapping(self):
        """Load a mapping from a file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load ABET Mapping",
            "",
            "JSON Files (*.json)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            mappings = data.get('mappings', {})
            self.set_mappings(mappings)

            QMessageBox.information(
                self,
                "Success",
                "ABET mapping loaded successfully."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load mapping: {str(e)}"
            )


class ABETReportDialog(QDialog):
    """Dialog for generating and viewing ABET reports."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_dir = None
        self.selected_mapping = None
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Generate ABET Assessment Report")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("ABET Assessment Report Generator")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(header)

        info_label = QLabel(
            "This tool analyzes your graded assessments and generates ABET outcome reports. "
            "You only need to grade once - the tool automatically calculates ABET data."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #757575; padding: 5px; margin-bottom: 10px;")
        layout.addWidget(info_label)

        # Course information
        course_group = QGroupBox("Course Information")
        course_layout = QVBoxLayout()

        # Course code
        code_layout = QHBoxLayout()
        code_layout.addWidget(QLabel("Course Code:"))
        self.course_code = QLineEdit()
        self.course_code.setPlaceholderText("e.g., CS 2500")
        code_layout.addWidget(self.course_code)
        course_layout.addLayout(code_layout)

        # Course name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Course Name:"))
        self.course_name = QLineEdit()
        self.course_name.setPlaceholderText("e.g., Algorithms")
        name_layout.addWidget(self.course_name)
        course_layout.addLayout(name_layout)

        # Semester
        semester_layout = QHBoxLayout()
        semester_layout.addWidget(QLabel("Semester:"))
        self.semester = QLineEdit()
        self.semester.setPlaceholderText("e.g., Fall 2024")
        semester_layout.addWidget(self.semester)
        course_layout.addLayout(semester_layout)

        # Assessment name
        assessment_layout = QHBoxLayout()
        assessment_layout.addWidget(QLabel("Assessment:"))
        self.assessment_name = QLineEdit()
        self.assessment_name.setPlaceholderText("e.g., Midterm 1")
        assessment_layout.addWidget(self.assessment_name)
        course_layout.addLayout(assessment_layout)

        # Target percentage
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("Target % (Proficient+):"))
        self.target_percentage = QLineEdit()
        self.target_percentage.setText("70")
        self.target_percentage.setMaximumWidth(60)
        target_layout.addWidget(self.target_percentage)
        target_layout.addWidget(QLabel("%"))
        target_layout.addStretch()
        course_layout.addLayout(target_layout)

        course_group.setLayout(course_layout)
        layout.addWidget(course_group)

        # Assessment selection
        assessment_group = QGroupBox("Assessment Data")
        assessment_layout = QVBoxLayout()

        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("Assessment directory:"))

        self.dir_label = QLabel("No directory selected")
        self.dir_label.setStyleSheet("color: #757575; font-style: italic;")
        select_layout.addWidget(self.dir_label)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.select_directory)
        select_layout.addWidget(browse_btn)

        assessment_layout.addLayout(select_layout)
        assessment_group.setLayout(assessment_layout)
        layout.addWidget(assessment_group)

        # Mapping selection
        mapping_group = QGroupBox("ABET Mapping")
        mapping_layout = QVBoxLayout()

        mapping_select_layout = QHBoxLayout()
        mapping_select_layout.addWidget(QLabel("Mapping file:"))

        self.mapping_label = QLabel("No mapping selected")
        self.mapping_label.setStyleSheet("color: #757575; font-style: italic;")
        mapping_select_layout.addWidget(self.mapping_label)

        mapping_browse_btn = QPushButton("Browse...")
        mapping_browse_btn.clicked.connect(self.select_mapping)
        mapping_select_layout.addWidget(mapping_browse_btn)

        mapping_layout.addLayout(mapping_select_layout)
        mapping_group.setLayout(mapping_layout)
        layout.addWidget(mapping_group)

        layout.addStretch()

        # Generate button
        generate_btn = QPushButton("Generate ABET Report")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 12px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        generate_btn.clicked.connect(self.generate_report)
        layout.addWidget(generate_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def select_directory(self):
        """Select the assessment directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Assessment Directory"
        )

        if directory:
            self.selected_dir = directory
            # Show just the folder name
            folder_name = os.path.basename(directory)
            self.dir_label.setText(folder_name)
            self.dir_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

    def select_mapping(self):
        """Select the ABET mapping file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ABET Mapping",
            "",
            "JSON Files (*.json)"
        )

        if file_path:
            self.selected_mapping = file_path
            # Show just the filename
            filename = os.path.basename(file_path)
            self.mapping_label.setText(filename)
            self.mapping_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

    def generate_report(self):
        """Generate the ABET report."""
        # Validation
        if not self.selected_dir:
            QMessageBox.warning(self, "Missing Information",
                                "Please select an assessment directory.")
            return

        if not self.selected_mapping:
            QMessageBox.warning(self, "Missing Information",
                                "Please select an ABET mapping file.")
            return

        if not self.course_code.text() or not self.assessment_name.text():
            QMessageBox.warning(self, "Missing Information",
                                "Please fill in course code and assessment name.")
            return

        try:
            target = float(self.target_percentage.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "Target percentage must be a number.")
            return

        # Generate report
        try:
            from src.tools.abet_tool import ABETMapping, ABETAssessmentAnalyzer, create_mapping_from_dict

            # Load mapping
            with open(self.selected_mapping, 'r') as f:
                mapping_data = json.load(f)

            mapping = create_mapping_from_dict(mapping_data)

            # Create analyzer
            analyzer = ABETAssessmentAnalyzer(mapping)

            # Load assessments with progress dialog
            progress = QProgressDialog("Loading assessments...", None, 0, 0, self)
            progress.setWindowTitle("Processing")
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            count = analyzer.load_assessments_from_directory(self.selected_dir)
            progress.close()

            if count == 0:
                QMessageBox.warning(
                    self,
                    "No Assessments Found",
                    "No valid assessment files were found in the selected directory."
                )
                return

            # Course info
            course_info = {
                'course_code': self.course_code.text(),
                'course_name': self.course_name.text(),
                'semester': self.semester.text(),
                'assessment': self.assessment_name.text(),
                'target_percentage': target
            }

            # Generate output filename
            safe_course = ''.join(c if c.isalnum() else '_' for c in self.course_code.text())
            safe_assessment = ''.join(c if c.isalnum() else '_' for c in self.assessment_name.text())
            default_filename = f"abet_report_{safe_course}_{safe_assessment}.json"

            # Ask where to save
            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save ABET Report",
                default_filename,
                "JSON Files (*.json)"
            )

            if not output_path:
                return

            # Generate report
            progress = QProgressDialog("Generating report...", None, 0, 0, self)
            progress.setWindowTitle("Processing")
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            report = analyzer.generate_abet_report(output_path, course_info)

            progress.close()

            # Show results dialog
            results_dialog = ABETResultsDialog(report, output_path, self)
            results_dialog.exec_()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to generate report:\n{str(e)}"
            )


class ABETResultsDialog(QDialog):
    """Dialog to display ABET report results."""

    def __init__(self, report, report_path, parent=None):
        super().__init__(parent)
        self.report = report
        self.report_path = report_path
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("ABET Assessment Report Results")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("ABET Assessment Report - Results")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(header)

        # Course info
        course_info = self.report.get('course_info', {})
        info_text = f"{course_info.get('course_code', 'N/A')} - {course_info.get('course_name', 'N/A')}"
        info_text += f"\n{course_info.get('assessment', 'N/A')} ({course_info.get('semester', 'N/A')})"
        info_text += f"\nStudents Assessed: {self.report.get('num_students', 0)}"

        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #757575; padding: 10px; background-color: #F5F5F5; border-radius: 4px;")
        layout.addWidget(info_label)

        # Results table
        self.create_results_table()
        layout.addWidget(self.table)

        # Summary text
        summary_group = QGroupBox("Detailed Summary")
        summary_layout = QVBoxLayout()

        summary_text = QTextEdit()
        summary_text.setReadOnly(True)
        summary_text.setPlainText(self.report.get('summary', ''))
        summary_text.setStyleSheet("font-family: 'Courier New', monospace;")
        summary_layout.addWidget(summary_text)

        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)

        # Saved location
        saved_label = QLabel(f"Report saved to: {self.report_path}")
        saved_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
        layout.addWidget(saved_label)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def create_results_table(self):
        """Create the results summary table."""
        self.table = QTableWidget()

        outcome_scores = self.report.get('outcome_scores', {})
        performance_levels = self.report.get('performance_levels', {})
        meets_targets = self.report.get('meets_targets', {})

        # Set up table
        num_outcomes = len(outcome_scores)
        self.table.setRowCount(num_outcomes)
        self.table.setColumnCount(6)

        headers = ["Outcome", "Mean", "Proficient+", "Target", "Meets Target?", "Distribution"]
        self.table.setHorizontalHeaderLabels(headers)

        # Populate table
        row = 0
        for outcome_id in sorted(outcome_scores.keys()):
            scores = outcome_scores[outcome_id]
            levels = performance_levels[outcome_id]
            target_info = meets_targets.get(outcome_id, {})

            # Outcome ID
            outcome_item = QTableWidgetItem(outcome_id)
            outcome_item.setFont(QFont("", -1, QFont.Bold))
            self.table.setItem(row, 0, outcome_item)

            # Mean
            mean_item = QTableWidgetItem(f"{scores['mean']:.1f}%")
            self.table.setItem(row, 1, mean_item)

            # Proficient or higher
            prof_plus = levels['proficient_or_higher']['percentage']
            prof_item = QTableWidgetItem(f"{prof_plus:.1f}%")

            # Color code based on performance
            if prof_plus >= 80:
                prof_item.setBackground(Qt.green)
            elif prof_plus >= 70:
                prof_item.setBackground(Qt.yellow)
            else:
                prof_item.setBackground(Qt.red)

            self.table.setItem(row, 2, prof_item)

            # Target
            target = target_info.get('target', 70)
            target_item = QTableWidgetItem(f"{target}%")
            self.table.setItem(row, 3, target_item)

            # Meets target
            meets = target_info.get('meets_target', False)
            meets_item = QTableWidgetItem("✓ Yes" if meets else "✗ No")
            meets_item.setFont(QFont("", -1, QFont.Bold))
            if meets:
                meets_item.setForeground(Qt.darkGreen)
            else:
                meets_item.setForeground(Qt.red)
            self.table.setItem(row, 4, meets_item)

            # Distribution
            dist_text = f"E:{levels['exemplary']['count']} "
            dist_text += f"P:{levels['proficient']['count']} "
            dist_text += f"D:{levels['developing']['count']} "
            dist_text += f"U:{levels['unsatisfactory']['count']}"
            dist_item = QTableWidgetItem(dist_text)
            self.table.setItem(row, 5, dist_item)

            row += 1

        # Adjust column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)