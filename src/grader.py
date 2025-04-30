import os
import json
import tempfile
import time
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QScrollArea,
                             QLineEdit, QMessageBox, QGroupBox, QCheckBox,
                             QSpinBox, QDialog, QFormLayout, QComboBox, QFrame)
from PyQt5.QtCore import Qt, QTimer, QPoint
import qtawesome as qta


from widgets.criterion_widget import CriterionWidget
from widgets.header_widget import HeaderWidget
from widgets.status_bar_widget import StatusBarWidget
from widgets.card_widget import CardWidget
from widgets.action_button import FloatingActionButton
from widgets.form_widgets import StyledFormLayout, FormField
from utils.rubric_parser import parse_rubric_file
from utils.pdf_generator import generate_assessment_pdf
from utils.styles import COLORS


class GradingConfigDialog(QDialog):
    """Dialog for configuring grading options."""

    def __init__(self, total_questions, parent=None):
        """Initialize the dialog with the number of available questions."""
        super().__init__(parent)
        self.total_questions = total_questions
        self.init_ui()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Rubric Grading Tool")
        self.setMinimumSize(1000, 700)


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

        # Save rubric as button (new)
        self.save_rubric_btn = QPushButton("Save Rubric As...")
        self.save_rubric_btn.setIcon(qta.icon('fa5s.save'))
        self.save_rubric_btn.clicked.connect(self.save_rubric_as)
        self.save_rubric_btn.setEnabled(False)
        rubric_layout.addWidget(self.save_rubric_btn)

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
        self.scroll_area.setMinimumHeight(300)  # Set a minimum height
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
        main_layout.addWidget(self.scroll_area)

        # Question summary widget with collapsible header
        self.question_summary_card = QWidget()
        self.question_summary_card.setStyleSheet("""
            QWidget {
                background-color: white;
                border-radius: 4px;
                border: 1px solid #EEEEEE;
                margin: 8px 0px;
            }
        """)
        question_summary_layout = QVBoxLayout(self.question_summary_card)
        question_summary_layout.setContentsMargins(0, 0, 0, 0)
        question_summary_layout.setSpacing(0)

        # Create collapsible header
        header_widget = QWidget()
        header_widget.setStyleSheet("""
            QWidget {
                background-color: #3F51B5;
                border-radius: 4px 4px 0 0;
            }
            QWidget:hover {
                background-color: #303F9F;
            }
        """)
        header_widget.setCursor(Qt.PointingHandCursor)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 8, 16, 8)

        # Add title
        title_label = QLabel("Question Scores Summary")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
        header_layout.addWidget(title_label)

        # Add toggle indicator
        self.toggle_indicator = QLabel("▼")  # Down arrow for collapse
        self.toggle_indicator.setStyleSheet("color: white; font-weight: bold;")
        header_layout.addWidget(self.toggle_indicator, 0, Qt.AlignRight)

        # Add header to layout
        question_summary_layout.addWidget(header_widget)

        # Create content container
        self.summary_content = QWidget()
        self.question_summary_layout = QVBoxLayout(self.summary_content)
        self.question_summary_layout.setContentsMargins(12, 12, 12, 12)
        question_summary_layout.addWidget(self.summary_content)

        # Add the card to main layout
        main_layout.addWidget(self.question_summary_card)
        self.question_summary_card.setVisible(False)

        # Connect header click for toggling
        self.summary_content_visible = True
        header_widget.mousePressEvent = self.toggle_summary_content

        # Bottom controls
        bottom_layout = QHBoxLayout()

        # Total points display
        self.total_label = QLabel("Total: 0 / 0 points")
        self.total_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        bottom_layout.addWidget(self.total_label)
        bottom_layout.addStretch()

        # Action buttons at the bottom
        button_container = QWidget()
        button_container.setObjectName("bottomButtonContainer")  # Add this line
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)

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
        save_btn.clicked.connect(self.save_assessment)
        button_layout.addWidget(save_btn)

        # Load assessment button
        load_assessment_btn = QPushButton("Load Assessment")
        load_assessment_btn.setIcon(qta.icon('fa5s.file-upload'))
        load_assessment_btn.clicked.connect(self.load_assessment)
        button_layout.addWidget(load_assessment_btn)

        bottom_layout.addWidget(button_container)

        main_layout.addLayout(bottom_layout)

        # Create and position the floating action button for saving
        self.save_fab = FloatingActionButton("save")
        self.save_fab.setIcon(qta.icon('fa5s.save', color='white'))
        self.save_fab.setToolTip("Save Assessment")
        self.save_fab.clicked.connect(self.save_assessment)
        self.save_fab.setParent(self)  # Must be parented to the main window

    def toggle_summary_content(self, event):
        """Toggle the visibility of the question summary content."""
        self.summary_content_visible = not self.summary_content_visible
        self.summary_content.setVisible(self.summary_content_visible)

        # Update the indicator
        if self.summary_content_visible:
            self.toggle_indicator.setText("▼")  # Down arrow
        else:
            self.toggle_indicator.setText("▶")  # Right arrow

        # Adjust the window to show more of the grading area
        if not self.summary_content_visible:
            # Add some delay to let the UI update
            QTimer.singleShot(100, self.adjust_window_for_grading)

    def adjust_window_for_grading(self):
        """Adjust the window to show more of the grading area."""
        # Find the criteria scroll area and give it more space
        if hasattr(self, 'scroll_area'):
            self.scroll_area.setMinimumHeight(350)  # Set a larger minimum height

    def update_fixed_total(self):
        """Update the fixed total based on questions and points per question."""
        self.fixed_total.setValue(self.questions_to_count.value() * self.points_per_question.value())

    def get_config(self):
        """Return the configuration as a dictionary."""
        return {
            "grading_mode": self.grading_mode.currentData(),
            "questions_to_count": self.questions_to_count.value(),
            "points_per_question": self.points_per_question.value(),
            "use_fixed_total": self.use_fixed_total.isChecked(),
            "fixed_total": self.fixed_total.value()
        }


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

        self.init_ui()
        self.setup_auto_save()
        self.check_for_recovery_files()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Rubric Grading Tool")
        self.setMinimumSize(1000, 700)

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

        # Save rubric as button (new)
        self.save_rubric_btn = QPushButton("Save Rubric As...")
        self.save_rubric_btn.setIcon(qta.icon('fa5s.save'))
        self.save_rubric_btn.clicked.connect(self.save_rubric_as)
        self.save_rubric_btn.setEnabled(False)
        rubric_layout.addWidget(self.save_rubric_btn)

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
        main_layout.addWidget(self.scroll_area)

        # Question summary card
        self.question_summary_card = CardWidget("Question Scores Summary")
        self.question_summary_layout = self.question_summary_card.get_content_layout()
        self.question_summary_card.setVisible(False)
        main_layout.addWidget(self.question_summary_card)

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
        save_btn.clicked.connect(self.save_assessment)
        button_layout.addWidget(save_btn)

        # Load assessment button
        load_assessment_btn = QPushButton("Load Assessment")
        load_assessment_btn.setIcon(qta.icon('fa5s.file-upload'))
        load_assessment_btn.clicked.connect(self.load_assessment)
        button_layout.addWidget(load_assessment_btn)

        bottom_layout.addWidget(button_container)

        main_layout.addLayout(bottom_layout)

        # Create and position the floating action button for saving
        self.save_fab = FloatingActionButton("save")
        self.save_fab.setIcon(qta.icon('fa5s.save', color='white'))  # With white color
        self.save_fab.setToolTip("Save Assessment")
        self.save_fab.clicked.connect(self.save_assessment)
        self.save_fab.setParent(self)

    def showEvent(self, event):
        """Handle window show event to position floating buttons."""
        super().showEvent(event)

        # Position the FAB in the bottom right corner with margin
        margin = 24
        self.save_fab.move(
            self.width() - self.save_fab.width() - margin,
            self.height() - self.save_fab.height() - margin - self.status_bar.height()
        )

    def resizeEvent(self, event):
        """Handle window resize events."""
        super().resizeEvent(event)

        # Reposition the FAB when the window is resized
        if hasattr(self, 'save_fab'):
            margin = 24

            # Find bottom button container
            button_container = self.findChild(QWidget, "bottomButtonContainer")

            # If we found the button container, position above it
            if button_container:
                self.save_fab.move(
                    self.width() - self.save_fab.width() - margin,
                    button_container.mapToParent(QPoint(0, 0)).y() - self.save_fab.height() - margin
                )
            else:
                # Default positioning
                self.save_fab.move(
                    self.width() - self.save_fab.width() - margin,
                    self.height() - self.save_fab.height() - margin - self.status_bar.height() - 50
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

        # Get assessment data
        assessment_data = self.get_assessment_data(validate=False)
        if not assessment_data:
            return

        # Create a unique filename based on student name and timestamp
        student_name = self.student_name_edit.text() or "unnamed_student"
        student_name = ''.join(c if c.isalnum() else '_' for c in student_name)  # Sanitize filename
        timestamp = int(time.time())
        filename = f"autosave_{student_name}_{timestamp}.json"
        file_path = os.path.join(self.auto_save_dir, filename)

        # Add auto-save metadata
        assessment_data["auto_save"] = {
            "timestamp": timestamp,
            "rubric_path": self.rubric_file_path,
            "is_auto_save": True
        }

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

    def check_for_recovery_files(self):
        """Check for auto-save files that might need recovery on startup."""
        try:
            recovery_files = []
            cutoff_time = time.time() - (24 * 60 * 60)  # Files from last 24 hours

            for filename in os.listdir(self.auto_save_dir):
                if filename.startswith("autosave_") and filename.endswith(".json"):
                    file_path = os.path.join(self.auto_save_dir, filename)
                    mod_time = os.path.getmtime(file_path)

                    if mod_time > cutoff_time:
                        try:
                            with open(file_path, 'r') as file:
                                data = json.load(file)

                                # Extract student name and timestamp
                                student_name = data.get("student_name", "Unnamed Student")
                                timestamp = data.get("auto_save", {}).get("timestamp", 0)
                                if timestamp:
                                    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
                                    recovery_files.append((file_path, student_name, time_str))
                        except Exception:
                            # Skip invalid files
                            continue

            # If we found recovery files, ask the user
            if recovery_files:
                message = "Auto-saved assessments were found. Would you like to recover one?\n\n"
                for i, (_, student, time_str) in enumerate(recovery_files):
                    message += f"{i + 1}. {student} - {time_str}\n"

                reply = QMessageBox.question(
                    self,
                    "Recovery Available",
                    message,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    # Create a simple dialog to let user choose which file to recover
                    dialog = QDialog(self)
                    dialog.setWindowTitle("Select Recovery File")
                    dialog.setStyleSheet("""
                        QDialog {
                            background-color: white;
                        }
                        QLabel {
                            font-weight: bold;
                            margin-bottom: 10px;
                        }
                    """)
                    layout = QVBoxLayout(dialog)

                    # Add title
                    title = QLabel("Select an auto-saved assessment to recover:")
                    title.setProperty("labelType", "heading")
                    layout.addWidget(title)

                    # Add combo box
                    combo = QComboBox()
                    for _, student, time_str in recovery_files:
                        combo.addItem(f"{student} - {time_str}")
                    layout.addWidget(combo)

                    # Add buttons
                    buttons = QHBoxLayout()
                    ok_btn = QPushButton("Recover")
                    ok_btn.clicked.connect(dialog.accept)
                    cancel_btn = QPushButton("Cancel")
                    cancel_btn.setStyleSheet("""
                        QPushButton {
                            background-color: white;
                            color: #3F51B5;
                            border: 1px solid #3F51B5;
                        }
                        QPushButton:hover {
                            background-color: #E8EAF6;
                        }
                    """)
                    cancel_btn.clicked.connect(dialog.reject)
                    buttons.addWidget(cancel_btn)
                    buttons.addWidget(ok_btn)

                    layout.addLayout(buttons)

                    if dialog.exec_() == QDialog.Accepted:
                        index = combo.currentIndex()
                        if 0 <= index < len(recovery_files):
                            self.recover_auto_save_file(recovery_files[index][0])
        except Exception as e:
            # If anything goes wrong with recovery, just log it and continue
            print(f"Recovery check failed: {str(e)}")

    def recover_auto_save_file(self, file_path):
        """Load a specific auto-save file for recovery."""
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)

            # Check if we need to load the associated rubric first
            rubric_path = data.get("auto_save", {}).get("rubric_path")
            if rubric_path and os.path.exists(rubric_path):
                self.load_rubric(rubric_path)

            # Now load the assessment data
            self.student_name_edit.setText(data.get("student_name", ""))
            self.assignment_name_edit.setText(data.get("assignment_name", ""))

            # Load grading configuration if present
            if "grading_config" in data:
                self.grading_config = data["grading_config"]
                self.update_config_info()

            # Update question selection if it exists
            selected_questions = data.get("selected_questions", [])
            if hasattr(self, 'question_checkboxes') and selected_questions:
                for q, checkbox in self.question_checkboxes.items():
                    checkbox.setChecked(q in selected_questions)

            # Fill in criteria data
            criteria_data = data.get("criteria", [])
            if len(criteria_data) == len(self.criterion_widgets):
                for i, criterion_data in enumerate(criteria_data):
                    widget = self.criterion_widgets[i]
                    widget.set_data(criterion_data)

            self.update_total_points()
            self.status_bar.set_status("Assessment recovered from auto-save")
            self.status_bar.show_temporary_message("Assessment successfully recovered")
        except Exception as e:
            QMessageBox.warning(self, "Recovery Failed", f"Could not recover the auto-save: {str(e)}")

    def save_rubric_as(self):
        """Save the current rubric to a new file."""
        if not self.rubric_data:
            QMessageBox.warning(self, "Warning", "No rubric loaded to save.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Rubric As",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        # Ensure .json extension
        if not file_path.lower().endswith('.json'):
            file_path += '.json'

        # Get current rubric data with any modifications
        current_rubric = self.get_current_rubric_data()

        try:
            with open(file_path, 'w') as file:
                json.dump(current_rubric, file, indent=2)

            # Update the current rubric path
            self.rubric_file_path = file_path

            self.status_bar.set_status(f"Rubric saved as: {os.path.basename(file_path)}")
            self.status_bar.show_temporary_message("Rubric saved successfully")
            QMessageBox.information(self, "Success", "Rubric saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save rubric: {str(e)}")

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

    def load_rubric(self, file_path=None):
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
            self.rubric_data = parse_rubric_file(file_path)
            self.rubric_file_path = file_path
            self.setup_rubric_ui()
            self.export_btn.setEnabled(True)
            self.config_btn.setEnabled(True)
            self.save_rubric_btn.setEnabled(True)  # Enable Save As button
            self.status_bar.set_status(f"Loaded rubric: {os.path.basename(file_path)}")
            self.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")

            # Show grading config dialog for initial setup
            self.show_grading_config()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")

    def setup_rubric_ui(self):
        """Set up the UI based on the loaded rubric."""
        # Clear existing criteria
        self.clear_layout(self.criteria_layout)
        self.criterion_widgets = []
        self.question_groups = {}

        if not self.rubric_data or "criteria" not in self.rubric_data:
            self.status_bar.set_status("Invalid rubric format.")
            self.status_label.setText("Invalid rubric format.")
            return

        # Set assignment name if available
        if "title" in self.rubric_data and not self.assignment_name_edit.text():
            self.assignment_name_edit.setText(self.rubric_data["title"])

        # Extract main questions from criteria titles
        main_questions = self.extract_main_questions()

        # Create widgets for each criterion
        for criterion in self.rubric_data["criteria"]:
            criterion_widget = CriterionWidget(criterion)
            # Connect the signal to update total points when a criterion changes
            criterion_widget.points_changed.connect(self.update_total_points)
            self.criteria_layout.addWidget(criterion_widget)
            self.criterion_widgets.append(criterion_widget)

            # Group by main question
            title = criterion["title"]
            main_question = self.extract_question_number(title)

            if main_question:
                if main_question not in self.question_groups:
                    self.question_groups[main_question] = []

                self.question_groups[main_question].append(criterion_widget)

        # Set up question selection UI
        self.setup_question_selection()

        # Add stretch to push everything up
        self.criteria_layout.addStretch()

        # Update total points
        self.update_total_points()

        # Update config info with question count
        self.update_config_info()

    def extract_main_questions(self):
        """Extract and return list of main question identifiers from criteria titles."""
        main_questions = []

        for criterion in self.rubric_data["criteria"]:
            title = criterion["title"]
            main_question = self.extract_question_number(title)

            if main_question and main_question not in main_questions:
                main_questions.append(main_question)

        return sorted(main_questions)

    def extract_question_number(self, title):
        """Extract the main question number from a criterion title."""
        if not title.startswith("Question "):
            return None

        # Remove "Question " prefix
        question_id = title.split(":")[0].replace("Question ", "").strip()

        # Extract main number (1 from "1a", "1b", etc.)
        if len(question_id) > 1 and question_id[1].isalpha():
            return question_id[0]

        # Handle other formats
        for i, char in enumerate(question_id):
            if not char.isdigit():
                if i > 0:
                    return question_id[:i]
                break

        return question_id

    def setup_question_selection(self):
        """Set up checkboxes for selecting which questions the student attempted."""
        # Clear existing checkboxes
        self.clear_layout(self.question_selection_layout)

        grading_mode = self.grading_config["grading_mode"]
        questions_to_count = self.grading_config["questions_to_count"]

        # If we found multiple main questions, create checkboxes for selection
        if len(self.question_groups) > 1:
            self.question_selection_group.setVisible(True)
            self.question_checkboxes = {}

            # Helper text based on grading mode
            if grading_mode == "best_scores":
                helper_text = "Select ALL questions the student attempted:"
            else:
                helper_text = f"Select the {questions_to_count} questions to grade:"

            helper_label = QLabel(helper_text)
            helper_label.setStyleSheet("font-weight: bold; margin-bottom: 8px;")
            self.question_selection_layout.addWidget(helper_label)

            # Create a grid layout for checkboxes
            checkbox_layout = QHBoxLayout()
            checkbox_layout.setSpacing(16)

            for q in sorted(self.question_groups.keys()):
                checkbox = QCheckBox(f"Question {q}")
                checkbox.setChecked(True)  # Default to checked
                checkbox.setStyleSheet("""
                    QCheckBox {
                        font-size: 12px;
                        padding: 4px;
                    }
                    QCheckBox:hover {
                        background-color: #F5F5F5;
                        border-radius: 4px;
                    }
                """)
                checkbox.stateChanged.connect(self.update_total_points)
                checkbox_layout.addWidget(checkbox)
                self.question_checkboxes[q] = checkbox

            checkbox_layout.addStretch()
            self.question_selection_layout.addLayout(checkbox_layout)

            # Add select all/none buttons
            buttons_layout = QHBoxLayout()
            buttons_layout.addStretch()

            select_all_btn = QPushButton("Select All")
            select_all_btn.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    color: #3F51B5;
                    border: 1px solid #3F51B5;
                    min-width: 100px;
                }
            """)
            select_all_btn.clicked.connect(self.select_all_questions)
            buttons_layout.addWidget(select_all_btn)

            select_none_btn = QPushButton("Select None")
            select_none_btn.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    color: #757575;
                    border: 1px solid #BDBDBD;
                    min-width: 100px;
                }
            """)
            select_none_btn.clicked.connect(self.select_no_questions)
            buttons_layout.addWidget(select_none_btn)

            self.question_selection_layout.addLayout(buttons_layout)

        else:
            self.question_selection_group.setVisible(False)

        # Update the question summary display
        self.update_question_summary()

    def select_all_questions(self):
        """Select all question checkboxes."""
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(True)

    def select_no_questions(self):
        """Deselect all question checkboxes."""
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(False)

    def clear_layout(self, layout):
        """Clear all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()

            if widget:
                widget.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def get_selected_questions(self):
        """Get the list of selected question numbers."""
        # If no checkboxes were created, select all questions
        if not hasattr(self, 'question_checkboxes') or not self.question_checkboxes:
            return list(self.question_groups.keys())

        # Return the list of checked question numbers
        return [q for q, cb in self.question_checkboxes.items() if cb.isChecked()]

    def update_question_summary(self):
        """Update the question summary display showing scores per question."""
        # Clear existing summary
        self.clear_layout(self.question_summary_layout)

        if not self.question_groups:
            self.question_summary_card.setVisible(False)
            return

        self.question_summary_card.setVisible(True)

        # Calculate scores for each question
        question_scores = {}
        for q, widgets in self.question_groups.items():
            awarded = sum(widget.get_awarded_points() for widget in widgets)
            possible = sum(widget.get_possible_points() for widget in widgets)
            percentage = (awarded / possible * 100) if possible > 0 else 0
            question_scores[q] = (awarded, possible, percentage)

        # If no scores yet, show a placeholder message
        if not question_scores:
            no_data_label = QLabel("No questions have been scored yet.")
            no_data_label.setStyleSheet("color: #757575; font-style: italic; padding: 20px;")
            no_data_label.setAlignment(Qt.AlignCenter)
            self.question_summary_layout.addWidget(no_data_label)
            return

        # Create a styled table for the summary
        table_frame = QFrame()
        table_frame.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border-radius: 4px;
                    border: 1px solid #E0E0E0;
                }
            """)
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        # Table header
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #F5F5F5; border-bottom: 1px solid #E0E0E0;")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(16, 8, 16, 8)

        header_labels = ["Question", "Score", "Percentage", "Status"]
        widths = [1, 1, 1, 2]  # Relative widths

        for i, label_text in enumerate(header_labels):
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold;")
            label.setAlignment(Qt.AlignLeft if i == 3 else Qt.AlignCenter)
            header_layout.addWidget(label, widths[i])

        table_layout.addWidget(header_frame)

        # Determine which questions are counted in the final score
        questions_to_count = self.grading_config["questions_to_count"]
        selected_questions = self.get_selected_questions()

        if self.grading_config["grading_mode"] == "best_scores":
            # Sort questions by percentage (highest first)
            sorted_questions = sorted(
                question_scores.items(),
                key=lambda x: x[1][2],
                reverse=True
            )

            # Use the best N questions from the selected ones
            best_questions = [q for q, _ in sorted_questions[:questions_to_count]
                              if q in selected_questions]
        else:
            # Use exactly the selected questions
            best_questions = selected_questions

        # Add table rows for each question
        for q in sorted(question_scores.keys()):
            awarded, possible, percentage = question_scores[q]

            row_frame = QFrame()
            row_frame.setStyleSheet("""
                QFrame:hover {
                    background-color: #F5F5F5;
                }
                QFrame {
                    border-bottom: 1px solid #EEEEEE;
                }
            """)
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(16, 12, 16, 12)

            # Question number
            q_label = QLabel(f"Question {q}")
            q_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(q_label, widths[0])

            # Score
            score_label = QLabel(f"{awarded} / {possible}")
            score_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(score_label, widths[1])

            # Percentage
            pct_label = QLabel(f"{percentage:.1f}%")
            pct_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(pct_label, widths[2])

            # Status (counted in final score or not)
            status_label = QLabel()
            status_label.setAlignment(Qt.AlignLeft)

            if q in selected_questions:
                if q in best_questions:
                    status = "Counted in final score"
                    status_label.setText(status)
                    status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")  # Green
                else:
                    status = "Selected but not counted (better scores exist)"
                    status_label.setText(status)
                    status_label.setStyleSheet("color: #FF9800;")  # Orange
            else:
                status = "Not selected for grading"
                status_label.setText(status)
                status_label.setStyleSheet("color: #9E9E9E;")  # Gray

            row_layout.addWidget(status_label, widths[3])

            table_layout.addWidget(row_frame)

        self.question_summary_layout.addWidget(table_frame)

        # Add note about best scores if applicable
        if self.grading_config["grading_mode"] == "best_scores":
            note_frame = QFrame()
            note_frame.setStyleSheet("""
                QFrame {
                    background-color: #E8EAF6;
                    border-radius: 4px;
                    padding: 8px;
                    margin-top: 12px;
                }
            """)
            note_layout = QVBoxLayout(note_frame)

            note = QLabel(f"Note: Final score uses the {questions_to_count} highest-scoring questions.")
            note.setStyleSheet("color: #3F51B5; font-style: italic;")
            note_layout.addWidget(note)

            self.question_summary_layout.addWidget(note_frame)

    def update_total_points(self):
        """Update the total points display based on selected questions and mode."""
        if not self.criterion_widgets:
            self.total_label.setText("Total: 0 / 0 points")
            return

        selected_questions = self.get_selected_questions()

        # Count how many selected questions we have
        num_selected = len(selected_questions)
        questions_to_count = self.grading_config["questions_to_count"]
        grading_mode = self.grading_config["grading_mode"]

        # Handle based on grading mode
        if grading_mode == "selected" and num_selected != questions_to_count:
            # In "selected" mode, we need exactly the right number
            self.total_label.setText(f"Please select exactly {questions_to_count} questions " +
                                     f"(currently {num_selected} selected)")
            self.total_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 14pt;")  # Red
            return
        elif grading_mode == "best_scores" and num_selected < 1:
            # In "best_scores" mode, we need at least one selection
            self.total_label.setText("Please select at least one question to grade")
            self.total_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 14pt;")  # Red
            return

        # Calculate points for each selected question
        question_points = {}

        for q in selected_questions:
            if q in self.question_groups:
                q_widgets = self.question_groups[q]
                question_awarded = sum(widget.get_awarded_points() for widget in q_widgets)
                question_possible = sum(widget.get_possible_points() for widget in q_widgets)
                percentage = (question_awarded / question_possible * 100) if question_possible > 0 else 0
                question_points[q] = (question_awarded, question_possible, percentage)

        # Sort questions by score percentage (descending)
        sorted_questions = sorted(
            question_points.items(),
            key=lambda x: x[1][2],
            reverse=True
        )

        # Calculate total points based on grading mode
        if grading_mode == "best_scores":
            # Take the best N questions (limited by how many were selected)
            count_to_use = min(questions_to_count, len(sorted_questions))
            best_questions = sorted_questions[:count_to_use]
            earned_points = sum(points[0] for _, points in best_questions)

            if self.grading_config["use_fixed_total"]:
                possible_points = self.grading_config["fixed_total"]
            else:
                possible_points = sum(points[1] for _, points in best_questions)
        else:
            # Use exactly the selected questions
            earned_points = sum(points[0] for _, points in sorted_questions)

            if self.grading_config["use_fixed_total"]:
                possible_points = self.grading_config["fixed_total"]
            else:
                possible_points = sum(points[1] for _, points in sorted_questions)

        # Update the total display
        self.total_label.setText(f"Total: {earned_points} / {possible_points} points")

        # Update color based on score
        if possible_points > 0:
            percentage = (earned_points / possible_points) * 100
            if percentage >= 90:
                self.total_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14pt;")  # Green
            elif percentage >= 70:
                self.total_label.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 14pt;")  # Orange
            else:
                self.total_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 14pt;")  # Red

        # Update the question summary
        self.update_question_summary()

        # Trigger an auto-save when points are updated
        self.auto_save_assessment()

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

    def get_assessment_data(self, validate=True):
        """Gather all the assessment data."""
        if not self.rubric_data or not self.criterion_widgets:
            return None

        selected_questions = self.get_selected_questions()
        questions_to_count = self.grading_config["questions_to_count"]
        grading_mode = self.grading_config["grading_mode"]

        # Validate selections based on grading mode
        if validate:
            if grading_mode == "selected" and len(selected_questions) != questions_to_count:
                QMessageBox.warning(
                    self,
                    "Warning",
                    f"Please select exactly {questions_to_count} questions to grade."
                )
                return None
            elif grading_mode == "best_scores" and len(selected_questions) < 1:
                QMessageBox.warning(
                    self,
                    "Warning",
                    "Please select at least one question to grade."
                )
                return None

        # Calculate points for each selected question
        question_points = {}
        for q in selected_questions:
            if q in self.question_groups:
                q_widgets = self.question_groups[q]
                question_awarded = sum(widget.get_awarded_points() for widget in q_widgets)
                question_possible = sum(widget.get_possible_points() for widget in q_widgets)
                percentage = (question_awarded / question_possible * 100) if question_possible > 0 else 0
                question_points[q] = (question_awarded, question_possible, percentage)

        # Determine which questions count toward the final score
        if grading_mode == "best_scores":
            # Sort questions by percentage and take the best N
            sorted_questions = sorted(
                question_points.items(),
                key=lambda x: x[1][2],
                reverse=True
            )
            count_to_use = min(questions_to_count, len(sorted_questions))
            best_questions = [q for q, _ in sorted_questions[:count_to_use]]
        else:
            # Use all selected questions
            best_questions = selected_questions

        # Get data for all criteria, marking which ones are selected and counted
        criteria_data = []
        for widget in self.criterion_widgets:
            data = widget.get_data()

            # Determine if this criterion is part of a selected question
            title = data["title"]

            main_question = self.extract_question_number(title)
            is_selected = main_question in selected_questions
            is_counted = main_question in best_questions

            data["selected"] = is_selected
            data["counted"] = is_counted
            criteria_data.append(data)

        # Calculate final score
        counted_question_points = [points for q, points in question_points.items() if q in best_questions]
        earned_total = sum(points[0] for points in counted_question_points) if counted_question_points else 0

        if self.grading_config["use_fixed_total"]:
            possible_total = self.grading_config["fixed_total"]
        else:
            possible_total = sum(points[1] for points in counted_question_points) if counted_question_points else 0

        # Create question summary data for the report
        question_summary = []
        for q in sorted(self.question_groups.keys()):
            if q in question_points:
                points = question_points[q]
                question_summary.append({
                    "question": q,
                    "awarded": points[0],
                    "possible": points[1],
                    "percentage": points[2],
                    "selected": True,
                    "counted": q in best_questions
                })
            else:
                # Question not attempted/selected
                q_widgets = self.question_groups[q]
                possible = sum(widget.get_possible_points() for widget in q_widgets)
                question_summary.append({
                    "question": q,
                    "awarded": 0,
                    "possible": possible,
                    "percentage": 0,
                    "selected": False,
                    "counted": False
                })

        return {
            "student_name": self.student_name_edit.text(),
            "assignment_name": self.assignment_name_edit.text(),
            "criteria": criteria_data,
            "selected_questions": selected_questions,
            "counted_questions": best_questions,
            "question_summary": question_summary,
            "grading_config": self.grading_config,
            "total_awarded": earned_total,
            "total_possible": possible_total,
            "percentage": (earned_total / possible_total * 100) if possible_total > 0 else 0,
            "rubric_path": self.rubric_file_path  # Store the path to the rubric
        }

    def save_assessment(self):
        """Save the current assessment to a JSON file."""
        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to save.")
            return

        assessment_data = self.get_assessment_data()
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

            self.update_total_points()
            QMessageBox.information(self, "Success", "Assessment loaded successfully.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load assessment: {str(e)}")

    def export_to_pdf(self):
        """Export the assessment to a PDF file."""
        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to export.")
            return

        assessment_data = self.get_assessment_data()
        if not assessment_data:
            return

        # Default filename based on student and assignment
        default_name = ""
        student = self.student_name_edit.text()
        assignment = self.assignment_name_edit.text()
        if student and assignment:
            safe_student = ''.join(c if c.isalnum() else '_' for c in student)
            safe_assignment = ''.join(c if c.isalnum() else '_' for c in assignment)
            default_name = f"{safe_assignment}_{safe_student}.pdf"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to PDF",
            default_name,
            "PDF Files (*.pdf);;All Files (*)"
        )

        if not file_path:
            return

        # Ensure .pdf extension
        if not file_path.lower().endswith('.pdf'):
            file_path += '.pdf'

        try:
            generate_assessment_pdf(file_path, assessment_data)
            self.status_bar.show_temporary_message("PDF exported successfully")
            QMessageBox.information(self, "Success", "Assessment exported to PDF successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export to PDF: {str(e)}")

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