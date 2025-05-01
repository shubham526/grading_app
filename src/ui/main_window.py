"""
Main window implementation for the Rubric Grading Tool.
"""

import os
import time
import json
import tempfile

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea,
    QLineEdit, QMessageBox, QGroupBox,
    QFrame, QSplitter, QDialog
)
from PyQt5.QtCore import Qt, QTimer
import qtawesome as qta

# Import from core modules
from src.core.assessment import get_assessment_data, update_total_points
from src.core.grader import is_valid_assessment
from src.core.rubric import load_rubric_from_file

# Import from UI modules
from src.ui.widgets.header import HeaderWidget
from src.ui.widgets.status_bar import StatusBarWidget
from src.ui.widgets.card import CardWidget


# Import from utils
from src.utils.layout import setup_question_selection
from src.utils.styles import COLORS
from src.utils.pdf import export_to_pdf, batch_export_assessments

# Import from analytics
from src.analytics.data_processor import collect_assessments


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
        clear_btn.setIcon(qta.icon('fa5s.eraser'))
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #757575;
                border: 1px solid #BDBDBD;
                padding-left: 10px;
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

    def load_rubric(self, file_path=None, show_config_on_load=True):
        """Load a rubric from a file (JSON or CSV)."""
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Rubric File",
                "",
                "Rubric Files (*.json *.csv);;JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
            )

        if not file_path:
            return

        try:
            # Use the existing function from core.rubric instead of reimplementing
            self.rubric_data = load_rubric_from_file(file_path)
            self.rubric_file_path = file_path

            # Use the existing function from utils.layout
            setup_question_selection(self)

            self.export_btn.setEnabled(True)
            self.config_btn.setEnabled(True)
            self.status_bar.set_status(f"Loaded rubric: {os.path.basename(file_path)}")
            self.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")
            self.analytics_btn.setEnabled(True)

            # Only show grading config if the flag is True
            if show_config_on_load:
                self.show_grading_config()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")

    def on_criterion_points_changed(self):
        """Handler for when criterion points are changed."""
        # Use the existing function instead of reimplementing
        update_total_points(self)

    def on_question_selection_changed(self):
        """Handler for when question selection is changed."""
        # Use the existing function instead of reimplementing
        update_total_points(self)

    def get_selected_questions(self):
        """Get the list of selected question numbers."""
        # If no checkboxes were created, select all questions
        if not hasattr(self, 'question_checkboxes') or not self.question_checkboxes:
            return list(self.question_groups.keys())

        # Return the list of checked question numbers
        return [q for q, cb in self.question_checkboxes.items() if cb.isChecked()]

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
        from src.ui.dialogs.config import GradingConfigDialog
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

            # Use existing function from utils.layout
            setup_question_selection(self)

            # Use existing function from core.assessment
            update_total_points(self)

    def show_analytics(self):
        """Show the analytics dialog with student performance data."""
        from src.ui.dialogs.analytics import AnalyticsDialog
        # Use the existing function from analytics module
        analytics_data = collect_assessments(self)

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

    def auto_save_assessment(self):
        """Automatically save the current assessment to a temporary file."""
        # Only auto-save if there's a rubric loaded and some data entered
        if not self.rubric_data or not self.criterion_widgets:
            return

        # Get assessment data without validation
        assessment_data = get_assessment_data(self, validate=False)
        if not assessment_data:
            return

        # Create a unique filename based on student name and timestamp
        student_name = self.student_name_edit.text() or "unnamed_student"
        student_name = ''.join(c if c.isalnum() else '_' for c in student_name)  # Sanitize filename
        timestamp = int(time.time())
        filename = f"autosave_{student_name}_{timestamp}.json"
        file_path = os.path.join(self.auto_save_dir, filename)

        try:
            with open(file_path, 'w') as file:
                json.dump(assessment_data, file, indent=2)

            # Update status bar
            current_time = time.strftime("%H:%M:%S")
            self.status_bar.set_auto_save_status(f"Saved at {current_time}")
            self.status_bar.show_temporary_message("Assessment auto-saved")

            # Clean up old auto-save files (keep only the 5 most recent)
            self.cleanup_auto_save_files()
        except Exception as e:
            self.status_bar.set_auto_save_status(f"Failed: {str(e)}", is_error=True)

    def cleanup_auto_save_files(self):
        """Remove old auto-save files, keeping only the most recent ones."""
        try:
            # Get all auto-save files for the current student
            student_name = self.student_name_edit.text() or "unnamed_student"
            student_name = ''.join(c if c.isalnum() else '_' for c in student_name)

            all_files = []
            for filename in os.listdir(self.auto_save_dir):
                if filename.startswith(f"autosave_{student_name}_") and filename.endswith(".json"):
                    file_path = os.path.join(self.auto_save_dir, filename)
                    all_files.append((file_path, os.path.getmtime(file_path)))

            # Sort by modification time (newest first)
            all_files.sort(key=lambda x: x[1], reverse=True)

            # Keep only the 5 most recent files
            for file_path, _ in all_files[5:]:
                os.remove(file_path)
        except Exception:
            # Silently fail - this is just cleanup
            pass

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

        # Use existing function from core.assessment
        update_total_points(self)

        # Reset current assessment path
        self.current_assessment_path = None

        # Update status
        self.status_bar.set_status("Form cleared")
        self.status_bar.show_temporary_message("Form has been cleared")

    def save_assessment(self):
        """Save the current assessment to a JSON file."""
        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to save.")
            return

        # Use existing function from core.assessment
        assessment_data = get_assessment_data(self)
        if not assessment_data:
            return

        # If we have a current path, use it as the default
        default_path = ""
        if self.current_assessment_path:
            default_path = self.current_assessment_path
        else:
            # Create a suggested filename based on student and assignment
            student = self.student_name_edit.text()
            assignment = self.assignment_name_edit.text()
            if student and assignment:
                safe_student = ''.join(c if c.isalnum() else '_' for c in student)
                safe_assignment = ''.join(c if c.isalnum() else '_' for c in assignment)
                default_path = f"{safe_assignment}_{safe_student}.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Assessment",
            default_path,
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        # Ensure .json extension
        if not file_path.lower().endswith('.json'):
            file_path += '.json'

        try:
            with open(file_path, 'w') as file:
                json.dump(assessment_data, file, indent=2)

            # Update current assessment path
            self.current_assessment_path = file_path

            # Update status
            self.status_bar.set_status(f"Saved to: {os.path.basename(file_path)}")
            self.status_bar.show_temporary_message("Assessment saved successfully")

            QMessageBox.information(self, "Success", "Assessment saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save assessment: {str(e)}")

    def load_assessment(self):
        """Load a previously saved assessment."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Assessment File",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as file:
                assessment_data = json.load(file)

            # Use existing function from core.grader
            if not is_valid_assessment(assessment_data):
                QMessageBox.warning(
                    self,
                    "Invalid Assessment",
                    "The selected file does not contain a valid assessment."
                )
                return

            # Check if we have a rubric file path in the assessment data
            rubric_path = assessment_data.get("rubric_path")

            # If the rubric isn't loaded or is different from the one in the assessment, try to load it
            if rubric_path and (not self.rubric_file_path or self.rubric_file_path != rubric_path):
                if os.path.exists(rubric_path):
                    reply = QMessageBox.question(
                        self,
                        "Load Rubric",
                        f"This assessment was created with a different rubric. Would you like to load the associated rubric?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes
                    )

                    if reply == QMessageBox.Yes:
                        self.load_rubric(rubric_path)
                else:
                    QMessageBox.warning(
                        self,
                        "Rubric Not Found",
                        f"The original rubric file could not be found. Please load the correct rubric first."
                    )

            # Check if we have a rubric loaded
            if not self.criterion_widgets:
                QMessageBox.warning(self, "Warning", "Please load a rubric first.")
                return

            # Fill in the form
            self.student_name_edit.setText(assessment_data.get("student_name", ""))
            self.assignment_name_edit.setText(assessment_data.get("assignment_name", ""))

            # Load grading configuration if present
            if "grading_config" in assessment_data:
                self.grading_config = assessment_data["grading_config"]
                self.update_config_info()

            # Update question selection if it exists
            selected_questions = assessment_data.get("selected_questions", [])
            if hasattr(self, 'question_checkboxes') and selected_questions:
                for q, checkbox in self.question_checkboxes.items():
                    checkbox.setChecked(q in selected_questions)

            # Fill in criteria data if it matches the current rubric
            criteria_data = assessment_data.get("criteria", [])
            if len(criteria_data) != len(self.criterion_widgets):
                QMessageBox.warning(
                    self,
                    "Warning",
                    "The assessment criteria don't match the current rubric."
                )
            else:
                for i, criterion_data in enumerate(criteria_data):
                    widget = self.criterion_widgets[i]
                    widget.set_data(criterion_data)

            # Update current assessment path
            self.current_assessment_path = file_path

            # Update status
            self.status_bar.set_status(f"Loaded from: {os.path.basename(file_path)}")
            self.status_bar.show_temporary_message("Assessment loaded successfully")

            # Use existing function from core.assessment
            update_total_points(self)

            QMessageBox.information(self, "Success", "Assessment loaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load assessment: {str(e)}")

    # Use existing functions from utils.pdf
    def export_to_pdf(self):
        export_to_pdf(self)

    def batch_export_assessments(self):
        batch_export_assessments(self)

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