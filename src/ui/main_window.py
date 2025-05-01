import os
import time
import json
import glob
import re
from datetime import datetime
import tempfile

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea,
    QLineEdit, QMessageBox, QGroupBox, QCheckBox,
    QSpinBox, QFrame, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressDialog, QDialog
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
import qtawesome as qta
import numpy as np
from matplotlib import pyplot as plt

# Import from core modules
from src.core.grader import extract_main_questions, extract_question_number
from src.core.assessment import get_assessment_data, update_total_points

# Import from UI modules
from src.ui.widgets.criterion import CriterionWidget
from src.ui.widgets.header import HeaderWidget
from src.ui.widgets.status_bar import StatusBarWidget
from src.ui.widgets.card import CardWidget
from src.ui.widgets.combobox import BetterComboBox

# Import from dialogs
from src.ui.dialogs.analytics import AnalyticsDialog
from src.ui.dialogs.config import GradingConfigDialog
from src.utils import parse_rubric_file

# Import from utils
from src.utils.file_io import (
    load_rubric_file, save_assessment_file, load_assessment_file,
    auto_save_assessment, cleanup_auto_save_files
)
from src.utils.pdf_generator import generate_assessment_pdf
from src.utils.layout import clear_layout
from src.utils.styles import COLORS

# Import from analytics
from src.analytics.data_processor import collect_assessments, process_question_data


class RubricGrader(QMainWindow):
    """Main application window for the Rubric Grading Tool."""

    def __init__(self):
        """Initialize the application window and UI components."""
        super().__init__()
        self.rubric_data = None
        self.criterion_widgets = []
        self.question_groups = {}  # Dictionary to group widgets by main question
        self.student_name = ""
        self.assignment_name = ""
        self.rubric_file_path = None  # Store the path to the loaded rubric
        self.current_assessment_path = None  # Path to the current assessment file
        self.auto_save_timer = None  # Timer for auto-saving
        self.auto_save_interval = 3 * 60 * 1000  # Auto-save every 3 minutes (in milliseconds)
        self.auto_save_dir = os.path.join(tempfile.gettempdir(), "rubric_grader_autosave")

        # Create auto-save directory if it doesn't exist
        if not os.path.exists(self.auto_save_dir):
            os.makedirs(self.auto_save_dir)

        # Default grading configuration
        self.grading_config = {
            "grading_mode": "best_scores",  # "selected" or "best_scores"
            "questions_to_count": 5,  # Number of questions to count in final score
            "points_per_question": 10,  # Default to 10 points per question
            "use_fixed_total": True,  # Use fixed total by default
            "fixed_total": 50  # Default to 50 points total
        }

        # Set window properties for better resizing
        self.setWindowTitle("Rubric Grading Tool")
        self.setMinimumSize(800, 600)  # Smaller minimum size
        self.resize(1000, 700)  # Default size

        self.init_ui()
        self.setup_auto_save()
        # Schedule the check using a timer after the constructor returns
        # Using a small delay (e.g., 50-100ms) ensures the main event loop is running
        # QTimer.singleShot(100, self.check_for_recovery_files)

    def init_ui(self):
        """Set up the user interface."""
        # Set up the status bar
        self.status_bar = StatusBarWidget(self)
        self.setStatusBar(self.status_bar)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)  # Add some padding

        # Add header
        self.header = HeaderWidget()
        main_layout.addWidget(self.header)

        # Add a divider
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet(f"background-color: {COLORS['divider'].name()};")
        main_layout.addWidget(divider)

        # Create a toolbar container
        toolbar_container = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(0, 8, 0, 8)

        # Rubric controls group
        rubric_group = QWidget()
        rubric_layout = QHBoxLayout(rubric_group)
        rubric_layout.setContentsMargins(0, 0, 0, 0)
        rubric_layout.setSpacing(8)

        # Load rubric button
        self.load_btn = QPushButton("Load Rubric")
        self.load_btn.setIcon(qta.icon('fa5s.folder-open'))
        self.load_btn.clicked.connect(self.load_rubric)
        rubric_layout.addWidget(self.load_btn)

        toolbar_layout.addWidget(rubric_group)

        # Add spacer
        toolbar_layout.addStretch()

        # Student and assignment info
        info_widget = QWidget()
        info_layout = QHBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(16)

        # Student name field with floating label
        student_container = QWidget()
        student_layout = QVBoxLayout(student_container)
        student_layout.setContentsMargins(0, 0, 0, 0)
        student_layout.setSpacing(4)

        student_label = QLabel("Student")
        student_label.setStyleSheet("color: #757575; font-size: 12px;")
        student_layout.addWidget(student_label)

        self.student_name_edit = QLineEdit()
        self.student_name_edit.setPlaceholderText("Enter student name")
        student_layout.addWidget(self.student_name_edit)

        info_layout.addWidget(student_container)

        # Assignment name field with floating label
        assignment_container = QWidget()
        assignment_layout = QVBoxLayout(assignment_container)
        assignment_layout.setContentsMargins(0, 0, 0, 0)
        assignment_layout.setSpacing(4)

        assignment_label = QLabel("Assignment")
        assignment_label.setStyleSheet("color: #757575; font-size: 12px;")
        assignment_layout.addWidget(assignment_label)

        self.assignment_name_edit = QLineEdit()
        self.assignment_name_edit.setPlaceholderText("Enter assignment name")
        assignment_layout.addWidget(self.assignment_name_edit)

        info_layout.addWidget(assignment_container)

        toolbar_layout.addWidget(info_widget)

        # Add spacer
        toolbar_layout.addStretch()

        # Action buttons
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        # debug_btn = QPushButton("Debug Analytics")
        # debug_btn.clicked.connect(self.debug_analytics)
        # actions_layout.addWidget(debug_btn)

        self.analytics_btn = QPushButton("Analytics")
        self.analytics_btn.setIcon(qta.icon('fa5s.chart-bar'))
        self.analytics_btn.clicked.connect(self.show_analytics)
        actions_layout.addWidget(self.analytics_btn)

        # Grading configuration button
        self.config_btn = QPushButton("Grading Config")
        self.config_btn.setIcon(qta.icon('fa5s.cog'))
        self.config_btn.clicked.connect(self.show_grading_config)
        self.config_btn.setEnabled(False)
        actions_layout.addWidget(self.config_btn)

        # Export button
        self.export_btn = QPushButton("Export to PDF")
        self.export_btn.setIcon(qta.icon('fa5s.file-export'))
        self.export_btn.clicked.connect(self.export_to_pdf)
        self.export_btn.setEnabled(False)
        actions_layout.addWidget(self.export_btn)

        toolbar_layout.addWidget(actions_widget)

        main_layout.addWidget(toolbar_container)

        # Status label with heading style
        self.status_label = QLabel("Please load a rubric to begin")
        self.status_label.setProperty("labelType", "heading")
        main_layout.addWidget(self.status_label)

        # Grading configuration card
        self.config_card = CardWidget("Grading Configuration")
        config_layout = self.config_card.get_content_layout()
        self.config_info = QLabel()
        config_layout.addWidget(self.config_info)
        main_layout.addWidget(self.config_card)
        self.update_config_info()

        # Questions selection group
        self.question_selection_group = QGroupBox("Questions Attempted by Student")
        self.question_selection_group.setStyleSheet("""
            QGroupBox {
                background-color: white;
                border-radius: 4px;
                margin-top: 16px;
            }
        """)
        self.question_selection_layout = QHBoxLayout()
        self.question_selection_group.setLayout(self.question_selection_layout)
        self.question_selection_group.setVisible(False)
        main_layout.addWidget(self.question_selection_group)

        # Scroll area for criteria with card-like appearance
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget#scrollContent {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #BDBDBD;
            }
        """)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")  # For styling
        self.criteria_layout = QVBoxLayout(self.scroll_content)
        self.criteria_layout.setContentsMargins(16, 16, 16, 16)  # Add padding
        self.scroll_area.setWidget(self.scroll_content)

        # Create the question summary card
        self.question_summary_card = CardWidget("Question Scores Summary")
        self.question_summary_layout = self.question_summary_card.get_content_layout()

        # Create a splitter to allow resizing between criteria and summary
        self.main_splitter = QSplitter(Qt.Vertical)

        # Add the criteria scroll area to the splitter
        self.main_splitter.addWidget(self.scroll_area)

        # Create a container for the summary section
        self.summary_container = QWidget()
        summary_layout = QVBoxLayout(self.summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)

        # Add the question summary card to the container
        summary_layout.addWidget(self.question_summary_card)

        # Add the summary container to the splitter
        self.main_splitter.addWidget(self.summary_container)

        # Set initial sizes (adjust as needed)
        self.main_splitter.setSizes([600, 200])

        # Add the splitter to the main layout
        main_layout.addWidget(self.main_splitter)

        # Bottom controls
        bottom_layout = QHBoxLayout()

        # Total points display
        self.total_label = QLabel("Total: 0 / 0 points")
        self.total_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        bottom_layout.addWidget(self.total_label)
        bottom_layout.addStretch()

        # Action buttons at the bottom
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        # Batch export button
        batch_export_btn = QPushButton("Batch Export")
        batch_export_btn.setIcon(qta.icon('fa5s.file-export'))
        batch_export_btn.setToolTip("Export multiple assessments to a directory")
        batch_export_btn.clicked.connect(self.batch_export_assessments)
        button_layout.addWidget(batch_export_btn)

        # Clear button
        clear_btn = QPushButton("Clear Form")
        clear_btn.setIcon(qta.icon('fa5s.eraser'))  # Add this line to set the eraser icon
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #757575;
                border: 1px solid #BDBDBD;
                padding-left: 10px;  /* Add padding to accommodate the icon */
            }
            QPushButton:hover {
                background-color: #F5F5F5;
            }
        """)
        clear_btn.clicked.connect(self.clear_form)
        button_layout.addWidget(clear_btn)

        # Save button
        save_btn = QPushButton("Save Assessment")
        save_btn.setIcon(qta.icon('fa5s.save'))
        save_btn.setToolTip("Save assessment to a file")
        save_btn.clicked.connect(self.save_assessment)
        button_layout.addWidget(save_btn)

        # Load assessment button
        load_assessment_btn = QPushButton("Load Assessment")
        load_assessment_btn.setIcon(qta.icon('fa5s.file-upload'))
        load_assessment_btn.clicked.connect(self.load_assessment)
        button_layout.addWidget(load_assessment_btn)

        bottom_layout.addWidget(button_container)

        main_layout.addLayout(bottom_layout)

    def debug_analytics(self):
        """
        Simple diagnostic function to directly analyze JSON files and display results.
        """
        # Let user select a directory containing assessments
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Assessment Directory",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if not directory:
            QMessageBox.warning(self, "Canceled", "Directory selection canceled.")
            return

        # Find all JSON files
        assessment_files = glob.glob(os.path.join(directory, "*.json"))

        if not assessment_files:
            QMessageBox.warning(
                self,
                "No Files Found",
                f"No JSON files found in {directory}"
            )
            return

        # Show how many files were found
        QMessageBox.information(
            self,
            "Files Found",
            f"Found {len(assessment_files)} JSON files in {directory}"
        )

        # Try to process the first file as a test
        try:
            with open(assessment_files[0], 'r') as file:
                data = json.load(file)

            # Show the structure
            structure_text = f"File: {os.path.basename(assessment_files[0])}\n\n"
            structure_text += f"Keys: {', '.join(data.keys())}\n\n"

            # Check for criteria
            if "criteria" in data:
                structure_text += f"Criteria count: {len(data['criteria'])}\n\n"

                # Look at the first criterion
                if data["criteria"]:
                    first_criterion = data["criteria"][0]
                    structure_text += f"First criterion keys: {', '.join(first_criterion.keys())}\n\n"
                    structure_text += f"Title: {first_criterion.get('title', 'N/A')}\n"
                    structure_text += f"Points: {first_criterion.get('points_awarded', 'N/A')} / {first_criterion.get('points_possible', 'N/A')}\n"

            # Display the structure
            QMessageBox.information(
                self,
                "JSON Structure",
                structure_text
            )

            # Try to count questions
            question_data = {}
            total_students = len(assessment_files)

            for file_path in assessment_files[:10]:  # Limit to 10 files for quick testing
                try:
                    with open(file_path, 'r') as file:
                        assessment = json.load(file)

                    for criterion in assessment.get("criteria", []):
                        title = criterion.get("title", "")
                        match = re.search(r"Question\s+(\d+)", title)

                        if match:
                            q_num = match.group(1)

                            if q_num not in question_data:
                                question_data[q_num] = {
                                    "scores": [],
                                    "title": title,
                                    "max_points": criterion.get("points_possible", 0)
                                }

                            question_data[q_num]["scores"].append(criterion.get("points_awarded", 0))
                except Exception as e:
                    print(f"Error processing {file_path}: {str(e)}")

            # Display found questions
            questions_text = f"Found {len(question_data)} questions across {min(total_students, 10)} assessments:\n\n"

            for q_num, data in question_data.items():
                questions_text += f"Question {q_num}:\n"
                questions_text += f"  Title: {data['title']}\n"
                questions_text += f"  Scores: {data['scores']}\n"
                questions_text += f"  Max Points: {data['max_points']}\n\n"

            QMessageBox.information(
                self,
                "Question Data",
                questions_text
            )

            # Create a simple matplotlib plot directly
            if question_data:
                plt.figure(figsize=(10, 6))

                # Get the first question for testing
                first_q = list(question_data.keys())[0]
                q_data = question_data[first_q]

                # Calculate percentages
                percentages = []
                for score in q_data["scores"]:
                    if q_data["max_points"] > 0:
                        percentages.append((score / q_data["max_points"]) * 100)
                    else:
                        percentages.append(0)

                # Create histogram
                plt.hist(percentages, bins=5, alpha=0.7, range=(0, 100),
                         color='blue', edgecolor='black')

                plt.title(f"Score Distribution for {q_data['title']}")
                plt.xlabel("Score (%)")
                plt.ylabel("Number of Students")
                plt.grid(axis='y', alpha=0.75)

                # Save to a file
                output_file = os.path.join(directory, "histogram_test.png")
                plt.savefig(output_file)
                plt.close()

                QMessageBox.information(
                    self,
                    "Plot Created",
                    f"Created a test histogram at:\n{output_file}"
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Processing JSON",
                f"Error: {str(e)}"
            )










    def show_analytics(self):
        """Show the analytics dialog with student performance data."""
        # Gather analytics data
        analytics_data = self.collect_assessments()

        if analytics_data:
            # Create and show dialog
            dialog = AnalyticsDialog(self, analytics_data)
            dialog.exec_()
        else:
            QMessageBox.warning(
                self,
                "No Data Available",
                "No assessment data was found or selected. Please try again."
            )

    def setup_auto_save(self):
        """Set up the auto-save timer."""
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.auto_save_assessment)
        self.auto_save_timer.start(self.auto_save_interval)








    def get_current_rubric_data(self):
        """Gather the current rubric data with any modifications."""
        if not self.rubric_data:
            return None

        # Create a copy of the original data
        current_rubric = self.rubric_data.copy()

        # Update criteria based on UI state
        for i, widget in enumerate(self.criterion_widgets):
            # Get the original criterion data
            criterion = current_rubric["criteria"][i]

            # Currently, we're not modifying the criterion data from the UI
            # This could be expanded to allow editing criteria directly

        return current_rubric

    def update_config_info(self):
        """Update the displayed grading configuration info."""
        if not self.grading_config:
            self.config_info.setText("")
            return

        config = self.grading_config
        total_questions = len(self.question_groups) if self.question_groups else "?"

        # Build info text based on grading mode
        if config["grading_mode"] == "best_scores":
            info = (f"Grading Mode: Using best {config['questions_to_count']} of {total_questions} "
                    f"questions for final score")
        else:
            info = (f"Grading Mode: Counting only {config['questions_to_count']} selected questions")

        # Add points information
        if config["use_fixed_total"]:
            info += f"<br>Total possible: {config['fixed_total']} points"
        else:
            total = config['questions_to_count'] * config['points_per_question']
            info += f"<br>{config['points_per_question']} points per question (Total: {total} points)"

        self.config_info.setText(info)
        self.config_info.setTextFormat(Qt.RichText)

    def show_grading_config(self):
        """Show dialog to configure grading options."""
        if not self.question_groups:
            QMessageBox.warning(self, "Warning", "Please load a rubric first.")
            return

        dialog = GradingConfigDialog(len(self.question_groups), self)

        # Set current values
        index = dialog.grading_mode.findData(self.grading_config["grading_mode"])
        if index >= 0:
            dialog.grading_mode.setCurrentIndex(index)

        dialog.questions_to_count.setValue(self.grading_config["questions_to_count"])
        dialog.points_per_question.setValue(self.grading_config["points_per_question"])
        dialog.use_fixed_total.setChecked(self.grading_config["use_fixed_total"])
        dialog.fixed_total.setValue(self.grading_config["fixed_total"])

        if dialog.exec_() == QDialog.Accepted:
            self.grading_config = dialog.get_config()
            self.update_config_info()

            # Update question selection UI
            self.setup_question_selection()

            # Update total points display
            self.update_total_points()











    def clear_form(self):
        """Clear all entered data."""
        self.student_name_edit.clear()
        self.assignment_name_edit.clear()

        for widget in self.criterion_widgets:
            widget.reset()

        # Reset checkboxes if they exist
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(True)

        self.update_total_points()

        # Reset current assessment path
        self.current_assessment_path = None

        # Update status
        self.status_bar.set_status("Form cleared")
        self.status_bar.show_temporary_message("Form has been cleared")







    def closeEvent(self, event):
        """Handle application close event to check for unsaved changes."""
        # Check if we have unsaved changes
        if self.rubric_data and self.criterion_widgets:
            # Perform one final auto-save
            self.auto_save_assessment()

            # Check if there are unsaved changes (if auto-save is disabled)
            if self.current_assessment_path is None:
                reply = QMessageBox.question(
                    self,
                    "Save Before Closing",
                    "There are unsaved changes. Would you like to save before closing?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    self.save_assessment()
                    event.accept()
                elif reply == QMessageBox.Cancel:
                    event.ignore()
                else:
                    event.accept()
            else:
                event.accept()
        else:
            event.accept()