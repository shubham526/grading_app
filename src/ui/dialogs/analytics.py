import numpy as np
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QWidget, QHBoxLayout, QLabel, QCheckBox, QSlider, \
    QDialogButtonBox
from src.ui.widgets.canvas import MatplotlibCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
from PyQt5.QtCore import Qt, QTimer, QEvent

from src.ui.widgets.combobox import BetterComboBox


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