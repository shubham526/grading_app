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