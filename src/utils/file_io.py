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

        # Only show grading config if the flag is True
        if show_config_on_load:
            self.show_grading_config()

    except Exception as e:
        QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")





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
        # assessment_data["auto_save"] = {
        #     "timestamp": timestamp,
        #     "rubric_path": self.rubric_file_path,
        #     "is_auto_save": True
        # }

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
