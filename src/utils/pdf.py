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
                    from src.utils.pdf_generator import generate_assessment_pdf
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