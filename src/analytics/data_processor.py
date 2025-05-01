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