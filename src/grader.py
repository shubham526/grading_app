
import tempfile
import time
from datetime import datetime
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QScrollArea,
                             QLineEdit, QMessageBox, QGroupBox, QCheckBox,
                             QSpinBox, QDialog, QFormLayout, QComboBox, QFrame, QDialogButtonBox, QSplitter,
                             QStyledItemDelegate, QListView)
from PyQt5.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QProgressDialog, QSlider)

from PyQt5.QtCore import Qt, QTimer, QEvent
import qtawesome as qta
from PyQt5.QtGui import QColor, QFont
import matplotlib.pyplot as plt

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import numpy as np
import re
import os
import json
import glob


from widgets.criterion_widget import CriterionWidget
from widgets.header_widget import HeaderWidget
from widgets.status_bar_widget import StatusBarWidget
from widgets.card_widget import CardWidget
from utils.rubric_parser import parse_rubric_file
from utils.pdf_generator import generate_assessment_pdf
from utils.styles import COLORS


class BetterComboBox(QComboBox):
    """A ComboBox with improved dropdown behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set a list view with better item rendering
        list_view = QListView()
        list_view.setTextElideMode(Qt.ElideNone)  # Prevent text from being cut off
        self.setView(list_view)

        # Use a delegate for better item display
        delegate = QStyledItemDelegate()
        self.setItemDelegate(delegate)

    def showPopup(self):
        """Improve popup display."""
        super().showPopup()
        popup = self.findChild(QFrame)
        if popup:
            # Make popup wider to ensure text fits
            width = max(self.width() + 50, 300)
            popup.setMinimumWidth(width)
            # Set a larger maximum height
            popup.setMaximumHeight(400)


class ImprovedComboBox(QComboBox):
    """Custom QComboBox with improved dropdown behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view().setMouseTracking(True)
        self.setItemDelegate(QStyledItemDelegate())

    def showPopup(self):
        """Override to improve popup behavior."""
        super().showPopup()
        # Make the popup slightly wider to prevent the scrollbar from hiding items
        popup = self.findChild(QFrame)
        if popup:
            width = max(self.width(), popup.width() + 20)  # Extra width for scrollbar
            popup.setFixedWidth(width)

    def eventFilter(self, watched, event):
        """Filter events for dropdown fixes."""
        if event.type() == QEvent.MouseMove:
            return False  # Don't filter mouse move events
        return super().eventFilter(watched, event)

# Create a canvas class for matplotlib
class MatplotlibCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, dpi=100):
        self.fig = Figure(figsize=(5, 4), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super(MatplotlibCanvas, self).__init__(self.fig)
        self.fig.tight_layout()


class AnalyticsDialog(QDialog):
    """Dialog for showing student performance analytics."""

    def __init__(self, parent=None, student_data=None):
        super().__init__(parent)
        self.student_data = student_data
        self.init_ui()

    def init_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Student Performance Analytics")
        self.setMinimumSize(800, 600)

        # Create layout
        layout = QVBoxLayout(self)

        # Create tabs for different analytics views
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create question performance tab
        question_tab = QWidget()
        question_layout = QVBoxLayout(question_tab)

        # Add chart selection controls
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Select Question:"))

        self.question_combo = BetterComboBox()
        if self.student_data and "question_data" in self.student_data:
            for q in sorted(self.student_data["question_data"].keys(), key=int):
                q_data = self.student_data["question_data"][q]
                title = q_data.get("title", f"Question {q}")
                self.question_combo.addItem(title)
        self.question_combo.currentIndexChanged.connect(self.update_chart)
        control_layout.addWidget(self.question_combo)

        # Fix for dropdown visibility issues
        self.question_combo.view().setMouseTracking(True)
        self.question_combo.view().viewport().installEventFilter(self)

        # Add normalization option
        self.normalize_cb = QCheckBox("Show as percentage")
        self.normalize_cb.setChecked(False)  # Default to actual counts
        self.normalize_cb.stateChanged.connect(self.update_chart)
        control_layout.addWidget(self.normalize_cb)

        # Add bin count slider
        control_layout.addWidget(QLabel("Bins:"))
        self.bin_slider = QSlider(Qt.Horizontal)
        self.bin_slider.setRange(3, 20)
        self.bin_slider.setValue(10)
        self.bin_slider.setMaximumWidth(100)
        self.bin_slider.valueChanged.connect(self.update_chart)
        control_layout.addWidget(self.bin_slider)

        control_layout.addStretch()
        question_layout.addLayout(control_layout)

        # Create matplotlib canvas for histogram
        self.canvas = MatplotlibCanvas(self)
        question_layout.addWidget(self.canvas)

        # Add toolbar
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        question_layout.addWidget(self.toolbar)
        for action in self.toolbar.actions():
            action.triggered.connect(self.update_chart)

        # Add stats
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("font-size: 12px; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        question_layout.addWidget(self.stats_label)

        self.tabs.addTab(question_tab, "Question Performance")

        # Create overall performance tab
        overall_tab = QWidget()
        overall_layout = QVBoxLayout(overall_tab)

        # Create canvas for overall performance
        self.overall_canvas = MatplotlibCanvas(self)
        overall_layout.addWidget(self.overall_canvas)

        # Add toolbar
        self.overall_toolbar = NavigationToolbar2QT(self.overall_canvas, self)
        overall_layout.addWidget(self.overall_toolbar)

        # Add overall stats
        self.overall_stats_label = QLabel()
        self.overall_stats_label.setStyleSheet(
            "font-size: 12px; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        overall_layout.addWidget(self.overall_stats_label)

        self.tabs.addTab(overall_tab, "Overall Performance")

        # Add file info
        file_info = QLabel()
        if self.student_data and "file_count" in self.student_data:
            file_info.setText(f"Analyzing {self.student_data['file_count']} assessment files")
        else:
            file_info.setText("No assessment files loaded")
        file_info.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(file_info)

        # Add button box
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Initialize charts
        self.update_chart()
        self.update_overall_chart()

    def update_chart(self):
        """Update the question performance chart."""
        if not self.student_data or "question_data" not in self.student_data:
            return

        # Clear the canvas
        self.canvas.axes.clear()

        # Get selected question
        q_idx = self.question_combo.currentIndex()
        if q_idx < 0:
            return

        q_key = sorted(self.student_data["question_data"].keys(), key=int)[q_idx]
        q_data = self.student_data["question_data"][q_key]

        # Get scores
        scores = q_data["scores"]
        max_points = q_data["max_points"]

        # Calculate percentages
        percentages = []
        for score in scores:
            if max_points > 0:
                percentages.append((score / max_points) * 100)
            else:
                percentages.append(0)

        # Get bin count
        bins = self.bin_slider.value()

        # Plot histogram
        if self.normalize_cb.isChecked():
            # Plot normalized (percentage) histogram
            n, bins, patches = self.canvas.axes.hist(percentages, bins=bins, alpha=0.7,
                                                     range=(0, 100), density=True,
                                                     color='#3F51B5', edgecolor='black')
            self.canvas.axes.set_xlabel('Score (%)')
            self.canvas.axes.set_ylabel('Frequency Density')
        else:
            # Plot count histogram
            n, bins, patches = self.canvas.axes.hist(percentages, bins=bins, alpha=0.7,
                                                     range=(0, 100), density=False,
                                                     color='#3F51B5', edgecolor='black')
            self.canvas.axes.set_xlabel('Score (%)')
            self.canvas.axes.set_ylabel('Number of Students')

        # Add grid
        self.canvas.axes.grid(axis='y', alpha=0.75)

        # Set title
        question_title = q_data.get("title", f"Question {q_key}")
        self.canvas.axes.set_title(question_title)

        # Calculate statistics
        mean = np.mean(percentages) if percentages else 0
        median = np.median(percentages) if percentages else 0
        std_dev = np.std(percentages) if percentages else 0

        # Update stats label
        stats_text = f"Statistics: Mean: {mean:.1f}% | Median: {median:.1f}% | Standard Deviation: {std_dev:.1f}% | Sample Size: {len(percentages)}"
        self.stats_label.setText(stats_text)

        # Refresh the canvas
        self.canvas.draw()

    def update_overall_chart(self):
        """Update the overall performance chart."""
        if not self.student_data or "question_data" not in self.student_data:
            return

        # Clear the canvas
        self.overall_canvas.axes.clear()

        # If we have direct overall scores, use them
        if "overall_data" in self.student_data and "overall_scores" in self.student_data["overall_data"]:
            overall_scores = self.student_data["overall_data"]["overall_scores"]
        else:
            # Otherwise calculate overall scores from individual questions
            # Get all student scores by percentage
            student_count = 0
            for q, q_data in self.student_data["question_data"].items():
                scores = q_data.get("scores", [])
                student_count = max(student_count, len(scores))

            # Create overall scores by averaging each student's question percentages
            overall_scores = []
            for i in range(student_count):
                student_percentages = []
                total_points = 0
                earned_points = 0

                for q, q_data in self.student_data["question_data"].items():
                    if i < len(q_data.get("scores", [])):
                        points = q_data.get("max_points", 0)
                        if points > 0:
                            total_points += points
                            earned_points += q_data["scores"][i]

                if total_points > 0:
                    overall_percentage = (earned_points / total_points) * 100
                    overall_scores.append(overall_percentage)

        # Plot histogram
        if overall_scores:
            n, bins, patches = self.overall_canvas.axes.hist(overall_scores, bins=10, alpha=0.7,
                                                             range=(0, 100), density=False,
                                                             color='#4CAF50', edgecolor='black')
            self.overall_canvas.axes.set_xlabel('Overall Score (%)')
            self.overall_canvas.axes.set_ylabel('Number of Students')
            self.overall_canvas.axes.set_title('Overall Score Distribution')

            # Add grid
            self.overall_canvas.axes.grid(axis='y', alpha=0.75)

            # Calculate statistics
            mean = np.mean(overall_scores) if overall_scores else 0
            median = np.median(overall_scores) if overall_scores else 0
            std_dev = np.std(overall_scores) if overall_scores else 0

            # Update stats label
            stats_text = f"Statistics: Mean: {mean:.1f}% | Median: {median:.1f}% | Standard Deviation: {std_dev:.1f}% | Sample Size: {len(overall_scores)}"
            self.overall_stats_label.setText(stats_text)
        else:
            # No data message
            self.overall_canvas.axes.text(0.5, 0.5, "No overall data available",
                                          ha='center', va='center', fontsize=14,
                                          transform=self.overall_canvas.axes.transAxes)

        # Refresh the canvas
        self.overall_canvas.draw()

    def eventFilter(self, watched, event):
        """Filter events for dropdown fixes."""
        # Fix for dropdown items being hidden when mouse hovers over them
        if hasattr(self, 'question_combo') and event.type() == QEvent.MouseMove and (
                watched == self.question_combo.view().viewport() or
                watched == self.question_combo.view()):
            return False  # Don't filter mouse move events in combobox
        return super().eventFilter(watched, event)

    def handle_toolbar_action(self, action):
        """Handle toolbar button clicks."""
        # This ensures the action is properly processed
        # Update chart after toolbar action
        QTimer.singleShot(100, self.update_chart)


class GradingConfigDialog(QDialog):
    """Dialog for configuring grading options."""

    def __init__(self, total_questions, parent=None):
        """Initialize the dialog with the number of available questions."""
        super().__init__(parent)
        self.total_questions = total_questions
        self.init_ui()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Grading Configuration")
        self.setMinimumWidth(400)

        # Create layout for the dialog
        layout = QVBoxLayout(self)

        # Add title
        title_label = QLabel("Configure Grading Options")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(title_label)

        # Create form for configuration options
        form = QFormLayout()
        form.setSpacing(10)

        # Grading mode selection
        self.grading_mode = QComboBox()
        self.grading_mode.addItem("Use best scores", "best_scores")
        self.grading_mode.addItem("Use selected questions", "selected")
        self.grading_mode.currentIndexChanged.connect(self.update_mode_description)
        form.addRow("Grading Mode:", self.grading_mode)

        # Mode description
        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("color: #757575; font-style: italic;")
        form.addRow("", self.mode_description)

        # Questions to count
        self.questions_to_count = QSpinBox()
        self.questions_to_count.setRange(1, self.total_questions)
        self.questions_to_count.setValue(min(5, self.total_questions))
        form.addRow("Questions to Count:", self.questions_to_count)

        # Points per question
        self.points_per_question = QSpinBox()
        self.points_per_question.setRange(1, 100)
        self.points_per_question.setValue(10)
        self.points_per_question.valueChanged.connect(self.update_fixed_total)
        form.addRow("Points per Question:", self.points_per_question)

        # Use fixed total option
        self.use_fixed_total = QCheckBox("Use fixed total points")
        self.use_fixed_total.setChecked(True)
        form.addRow("", self.use_fixed_total)

        # Fixed total
        self.fixed_total = QSpinBox()
        self.fixed_total.setRange(1, 1000)
        self.fixed_total.setValue(50)
        form.addRow("Fixed Total Points:", self.fixed_total)

        layout.addLayout(form)

        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Initial update of the mode description
        self.update_mode_description()

    def update_mode_description(self):
        """Update the description based on the selected grading mode."""
        mode = self.grading_mode.currentData()
        if mode == "best_scores":
            desc = "Automatically use the highest-scoring questions for the final grade."
        else:
            desc = "Only count questions that are explicitly selected for grading."
        self.mode_description.setText(desc)

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

        # Set window properties for better resizing
        self.setWindowTitle("Rubric Grading Tool")
        self.setMinimumSize(800, 600)  # Smaller minimum size
        self.resize(1000, 700)  # Default size

        self.init_ui()
        self.setup_auto_save()
        self.check_for_recovery_files()

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

        debug_btn = QPushButton("Debug Analytics")
        debug_btn.clicked.connect(self.debug_analytics)
        actions_layout.addWidget(debug_btn)

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

    def batch_export_assessments(self):
        """
        Batch export feature to save multiple student assessments to a designated directory.
        This creates a structured dataset that can be used for analytics.
        """
        # Open a dialog to select the export directory
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Export Directory",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if not export_dir:
            return

        # Create a dialog to get a list of assessment files
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Select Assessment Files")
        file_dialog.setFileMode(QFileDialog.ExistingFiles)
        file_dialog.setNameFilter("Assessment Files (*.json)")

        if not file_dialog.exec_():
            return

        selected_files = file_dialog.selectedFiles()

        if not selected_files:
            return

        # Create a subdirectory for the current date
        timestamp = datetime.now().strftime("%Y-%m-%d")
        batch_dir = os.path.join(export_dir, f"batch_{timestamp}")

        try:
            if not os.path.exists(batch_dir):
                os.makedirs(batch_dir)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to create export directory: {str(e)}"
            )
            return

        # Export each assessment
        progress = QProgressDialog("Exporting assessments...", "Cancel", 0, len(selected_files), self)
        progress.setWindowTitle("Batch Export")
        progress.setWindowModality(Qt.WindowModal)

        exported_count = 0

        for i, file_path in enumerate(selected_files):
            progress.setValue(i)
            if progress.wasCanceled():
                break

            try:
                with open(file_path, 'r') as file:
                    assessment = json.load(file)

                # Generate a filename for the output
                student_name = assessment.get("student_name", "unnamed")
                safe_student = ''.join(c if c.isalnum() else '_' for c in student_name)

                # Save JSON
                output_json = os.path.join(batch_dir, f"{safe_student}.json")
                with open(output_json, 'w') as file:
                    json.dump(assessment, file, indent=2)

                # Generate PDF if requested
                # (This functionality could be made optional with a checkbox)
                output_pdf = os.path.join(batch_dir, f"{safe_student}.pdf")
                try:
                    from utils.pdf_generator import generate_assessment_pdf
                    generate_assessment_pdf(output_pdf, assessment)
                except Exception as pdf_error:
                    print(f"PDF generation failed: {str(pdf_error)}")

                exported_count += 1

            except Exception as e:
                print(f"Error processing {file_path}: {str(e)}")

        progress.setValue(len(selected_files))

        # Create batch summary file
        try:
            summary_path = os.path.join(batch_dir, "batch_info.json")
            with open(summary_path, 'w') as file:
                summary = {
                    "export_date": timestamp,
                    "file_count": exported_count,
                    "assignment_name": self.assignment_name_edit.text() or "Unknown Assignment"
                }
                json.dump(summary, file, indent=2)
        except Exception as e:
            print(f"Failed to create batch summary: {str(e)}")

        # Show success message
        QMessageBox.information(
            self,
            "Export Complete",
            f"Successfully exported {exported_count} assessments to {batch_dir}"
        )

    def collect_assessments(self):
        """
        Collect and process assessment data from a directory of JSON files.
        Returns a dictionary with aggregated assessment data.
        """
        # Let user select a directory containing assessments
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Assessment Directory",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if not directory:
            return None

        # Find all assessment JSON files in the directory
        assessment_files = glob.glob(os.path.join(directory, "*.json"))

        if not assessment_files:
            QMessageBox.warning(
                self,
                "No Assessments Found",
                "No assessment files (*.json) were found in the selected directory."
            )
            return None

        # Initialize data structures
        question_data = {}
        assignment_name = ""
        total_students = len(assessment_files)

        # Process each assessment file
        progress = QProgressDialog("Loading assessments...", "Cancel", 0, len(assessment_files), self)
        progress.setWindowTitle("Loading Assessments")
        progress.setWindowModality(Qt.WindowModal)

        for i, file_path in enumerate(assessment_files):
            progress.setValue(i)
            if progress.wasCanceled():
                break

            try:
                with open(file_path, 'r') as file:
                    assessment = json.load(file)

                    # Use the assignment name from the first valid assessment
                    if not assignment_name and "assignment_name" in assessment:
                        assignment_name = assessment["assignment_name"]

                    # Process question data from criteria
                    for criterion in assessment.get("criteria", []):
                        title = criterion.get("title", "")
                        # Match question numbers like "Question 1: Topic" or "Question 1a"
                        match = re.search(r"Question\s+(\d+)", title)

                        if match:
                            q_num = match.group(1)

                            if q_num not in question_data:
                                question_data[q_num] = {
                                    "scores": [],
                                    "title": title,
                                    "max_points": criterion.get("points_possible", 0)
                                }

                            # Add score
                            question_data[q_num]["scores"].append(criterion.get("points_awarded", 0))

                            # Update max points if needed
                            if criterion.get("points_possible", 0) > question_data[q_num]["max_points"]:
                                question_data[q_num]["max_points"] = criterion.get("points_possible", 0)

            except Exception as e:
                print(f"Error processing {file_path}: {str(e)}")

        progress.setValue(len(assessment_files))

        # Calculate overall scores
        overall_scores = []
        for i in range(min(total_students, len(assessment_files))):
            # Try to get direct overall scores if available
            try:
                with open(assessment_files[i], 'r') as file:
                    assessment = json.load(file)

                if "total_awarded" in assessment and "total_possible" in assessment:
                    if assessment["total_possible"] > 0:
                        percentage = (assessment["total_awarded"] / assessment["total_possible"]) * 100
                        overall_scores.append(percentage)
                        continue

                # Otherwise calculate from criteria
                student_total_awarded = 0
                student_total_possible = 0

                for criterion in assessment.get("criteria", []):
                    student_total_awarded += criterion.get("points_awarded", 0)
                    student_total_possible += criterion.get("points_possible", 0)

                if student_total_possible > 0:
                    percentage = (student_total_awarded / student_total_possible) * 100
                    overall_scores.append(percentage)

            except Exception as e:
                print(f"Error calculating overall score for student {i + 1}: {str(e)}")

        # Return the collected data
        return {
            "question_data": question_data,
            "assignment_name": assignment_name,
            "file_count": len(assessment_files),
            "overall_data": {
                "overall_scores": overall_scores,
                "num_students": len(overall_scores)
            }
        }

    def process_question_data(self, question_data, assessment):
        """
        Process question data from an assessment with your specific JSON format.
        """
        for criterion in assessment.get("criteria", []):
            # Extract question number using regex
            title = criterion.get("title", "")
            match = re.search(r"Question\s+(\d+)", title)
            if not match:
                continue

            q_num = match.group(1)

            if q_num not in question_data:
                question_data[q_num] = {
                    "scores": [],
                    "percentages": [],
                    "max_points": criterion.get("points_possible", 0),
                    "num_students": 0,
                    "question_title": title
                }

            # Add score
            awarded = criterion.get("points_awarded", 0)
            possible = criterion.get("points_possible", 0)
            question_data[q_num]["scores"].append(awarded)

            # Calculate percentage
            if possible > 0:
                percentage = (awarded / possible) * 100
            else:
                percentage = 0
            question_data[q_num]["percentages"].append(percentage)

            # Update max points if needed
            if possible > question_data[q_num]["max_points"]:
                question_data[q_num]["max_points"] = possible

            # Increment student count
            question_data[q_num]["num_students"] += 1

    def is_valid_assessment(self, assessment):
        """
        Check if the given dictionary is a valid assessment.
        """
        # Check for minimum required fields for your JSON format
        required_fields = ["student_name", "criteria"]

        for field in required_fields:
            if field not in assessment:
                return False

        # Check if criteria contains question data
        has_questions = False
        for criterion in assessment.get("criteria", []):
            if "Question" in criterion.get("title", ""):
                has_questions = True
                break

        return has_questions

    def gather_analytics_data(self):
        """
        Gather data for analytics from loaded assessments.
        """
        # Try to collect real assessment data
        collected_data = self.collect_assessments()

        if collected_data:
            return collected_data

        # If user canceled or no data found, generate sample data
        # (same sample data generation as before)
        question_data = {}

        # Create sample data for each question
        for q in self.question_groups.keys():
            # Generate random scores (in a real app, these would come from saved assessments)
            num_students = 30  # Sample size
            max_points = sum(widget.get_possible_points() for widget in self.question_groups[q])

            # Generate random scores with a normal distribution
            mean_percent = 70  # Mean score (as percentage)
            std_dev = 15  # Standard deviation

            # Generate scores and clip to valid range
            scores = np.random.normal(mean_percent * max_points / 100,
                                      std_dev * max_points / 100,
                                      num_students)
            scores = np.clip(scores, 0, max_points)

            # Calculate percentages
            percentages = [(s / max_points * 100) for s in scores]

            question_data[q] = {
                "scores": scores,
                "percentages": percentages,
                "max_points": max_points,
                "num_students": num_students
            }

        # Generate overall scores
        overall_scores = np.random.normal(70, 15, num_students)
        overall_scores = np.clip(overall_scores, 0, 100)

        return {
            "question_data": question_data,
            "overall_data": {
                "overall_scores": overall_scores,
                "num_students": num_students
            },
            "assignment_name": "Sample Data"
        }

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
                    # Create a simple dialog to let user choose which file to recover
                    dialog = QDialog(self)
                    dialog.setWindowTitle("Select Recovery File")
                    dialog.setMinimumWidth(400)
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

                    # Create combo box
                    combo = QComboBox()
                    combo.setMinimumHeight(30)  # Make it taller
                    for _, student, time_str in recovery_files:
                        combo.addItem(f"{student} - {time_str}")
                    layout.addWidget(combo)

                    # Add some spacing
                    spacer = QWidget()
                    spacer.setMinimumHeight(20)
                    layout.addWidget(spacer)

                    # Add buttons
                    buttons = QHBoxLayout()
                    cancel_btn = QPushButton("Cancel")
                    cancel_btn.clicked.connect(dialog.reject)
                    buttons.addWidget(cancel_btn)

                    recover_btn = QPushButton("Recover")
                    recover_btn.clicked.connect(dialog.accept)
                    recover_btn.setStyleSheet("""
                        QPushButton {
                            background-color: #3F51B5;
                            color: white;
                        }
                    """)
                    buttons.addWidget(recover_btn)
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
            self.status_bar.set_status(f"Loaded rubric: {os.path.basename(file_path)}")
            self.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")
            self.analytics_btn.setEnabled(True)

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
        self.question_summary_card.setVisible(True)

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

        self.update_question_summary()

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
        """Update the question summary display using a proper QTableWidget."""
        # Clear existing summary
        self.clear_layout(self.question_summary_layout)

        if not self.question_groups:
            self.question_summary_card.setVisible(False)
            return

        # Make the card visible
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

        # Create a proper table widget for the summary
        table = QTableWidget()
        table.setColumnCount(4)
        table.setRowCount(len(question_scores))
        table.setHorizontalHeaderLabels(["Question", "Score", "Percentage", "Status"])

        # Set table properties
        table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #DDDDDD;
                gridline-color: #DDDDDD;
                background-color: white;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 6px;
                font-weight: bold;
                border: 1px solid #DDDDDD;
            }
        """)

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
        for row, q in enumerate(sorted(question_scores.keys())):
            awarded, possible, percentage = question_scores[q]

            # Question number
            q_item = QTableWidgetItem(f"Question {q}")
            q_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, q_item)

            # Score
            score_item = QTableWidgetItem(f"{awarded} / {possible}")
            score_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 1, score_item)

            # Percentage
            pct_item = QTableWidgetItem(f"{percentage:.1f}%")
            pct_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 2, pct_item)

            # Status
            if q in selected_questions:
                if q in best_questions:
                    status = "Counted in final score"
                    status_item = QTableWidgetItem(status)
                    status_item.setForeground(QColor("#4CAF50"))  # Green
                    status_item.setFont(QFont("", -1, QFont.Bold))
                else:
                    status = "Selected but not counted"
                    status_item = QTableWidgetItem(status)
                    status_item.setForeground(QColor("#FF9800"))  # Orange
            else:
                status = "Not selected for grading"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor("#9E9E9E"))  # Gray

            status_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(row, 3, status_item)

        # Auto-adjust column widths
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        # Add the table to the layout
        self.question_summary_layout.addWidget(table)

        # Add note about best scores if applicable
        if self.grading_config["grading_mode"] == "best_scores":
            note = QLabel(f"Note: Final score uses the {questions_to_count} highest-scoring questions.")
            note.setStyleSheet(
                "color: #3F51B5; font-style: italic; background-color: #E8EAF6; padding: 8px; border-radius: 4px;")
            self.question_summary_layout.addWidget(note)

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