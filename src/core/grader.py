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

    def is_valid_assessment(assessment):
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