"""
test_scoring.py
===============

Tests for the ABET scoring engine, validation engine, and outcome profile system.

Covers:
  - Criterion ID generation (src/core/utils.py)
  - Outcome scoring formula and no-splitting rule (src/tools/abet_scoring.py)
  - Evidence policies: counted_only, selected_only, all
  - Performance bands and adequate_or_higher rollup
  - Bonus/negative score clamping
  - check_targets and meets_target back-fill
  - Validation: duplicate IDs, unmapped criteria, unknown outcome IDs
  - OutcomeProfile loading, keyword inference, LO→SO crosswalk
  - Profile generalisation (non-CS2500 profile works identically)
  - Legacy abet_outcomes alias accepted in scoring
"""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Criterion ID generation
# ---------------------------------------------------------------------------

class TestCriterionIDGeneration(unittest.TestCase):

    def test_basic_title(self):
        from src.core.utils import generate_criterion_id
        self.assertEqual(generate_criterion_id("Question 2 - Runtime Analysis", 0),
                         "QUESTION_2_RUNTIME_ANALYSIS")

    def test_title_with_colon(self):
        from src.core.utils import generate_criterion_id
        self.assertEqual(generate_criterion_id("Q3: Correctness Proof", 1),
                         "Q3_CORRECTNESS_PROOF")

    def test_empty_title_uses_fallback(self):
        from src.core.utils import generate_criterion_id
        self.assertEqual(generate_criterion_id("", 7), "CRITERION_007")

    def test_none_title_uses_fallback(self):
        from src.core.utils import generate_criterion_id
        self.assertEqual(generate_criterion_id(None, 3), "CRITERION_003")

    def test_with_prefix(self):
        from src.core.utils import generate_criterion_id
        self.assertEqual(generate_criterion_id("Runtime Analysis", 0, "PS3"),
                         "PS3_RUNTIME_ANALYSIS")

    def test_special_characters_stripped(self):
        from src.core.utils import generate_criterion_id
        result = generate_criterion_id("Q2 – Greedy Choice (15 pts)", 0)
        self.assertNotIn("-", result)
        self.assertNotIn("(", result)
        self.assertIn("Q2", result)
        self.assertIn("GREEDY", result)


# ---------------------------------------------------------------------------
# Outcome scoring — no-splitting rule and formula
# ---------------------------------------------------------------------------

class TestOutcomeScoring(unittest.TestCase):

    def _crit(self, awarded, possible, outcomes, outcome_key="abet_outcomes"):
        return {
            "id": "C1", "title": "T",
            "points_awarded": awarded, "points_possible": possible,
            "course_outcomes": [], "abet_outcomes": [],
            "program_outcomes": [], "assessment_tags": [],
            outcome_key: outcomes,
            "selected": True, "counted": True,
        }

    def test_single_criterion_two_outcomes_no_splitting(self):
        """8/10 mapped to SO1 and SO6 → both 80%, not 40%."""
        from src.tools.abet_scoring import score_student_outcomes
        scores = score_student_outcomes(
            [self._crit(8, 10, ["SO1", "SO6"])], "abet_outcomes")
        self.assertAlmostEqual(scores["SO1"], 80.0, places=5)
        self.assertAlmostEqual(scores["SO6"], 80.0, places=5)

    def test_perfect_score_gives_100(self):
        from src.tools.abet_scoring import score_student_outcomes
        scores = score_student_outcomes(
            [self._crit(10, 10, ["SO1"])], "abet_outcomes")
        self.assertAlmostEqual(scores["SO1"], 100.0, places=5)

    def test_zero_score_gives_zero(self):
        from src.tools.abet_scoring import score_student_outcomes
        scores = score_student_outcomes(
            [self._crit(0, 10, ["SO1"])], "abet_outcomes")
        self.assertAlmostEqual(scores["SO1"], 0.0, places=5)

    def test_unmapped_outcome_absent(self):
        from src.tools.abet_scoring import score_student_outcomes
        scores = score_student_outcomes(
            [self._crit(8, 10, ["SO1"])], "abet_outcomes")
        self.assertNotIn("SO6", scores)

    def test_lo_scoring(self):
        from src.tools.abet_scoring import score_student_outcomes
        c = self._crit(6, 10, ["LO1", "LO4"], "course_outcomes")
        scores = score_student_outcomes([c], "course_outcomes")
        self.assertAlmostEqual(scores["LO1"], 60.0, places=5)
        self.assertAlmostEqual(scores["LO4"], 60.0, places=5)

    def test_two_criteria_same_outcome_weighted_sum(self):
        """C1: 8/10 + C2: 3/5 → LO1 = 11/15 = 73.33%."""
        from src.tools.abet_scoring import calculate_lo_scores
        assessments = [{"student_name": "Alice", "criteria": [
            {"id": "C1", "title": "C1", "points_awarded": 8, "points_possible": 10,
             "course_outcomes": ["LO1"], "abet_outcomes": [],
             "selected": True, "counted": True},
            {"id": "C2", "title": "C2", "points_awarded": 3, "points_possible": 5,
             "course_outcomes": ["LO1"], "abet_outcomes": [],
             "selected": True, "counted": True},
        ]}]
        scores = calculate_lo_scores(assessments)
        self.assertAlmostEqual(scores["LO1"]["mean"], 11 / 15 * 100, places=3)

    def test_multiple_students_mean(self):
        """Alice 80% + Bob 60% → mean 70%."""
        from src.tools.abet_scoring import calculate_so_scores
        def _a(name, pts):
            return {"student_name": name, "criteria": [
                {"id": "C1", "title": "T", "points_awarded": pts, "points_possible": 10,
                 "abet_outcomes": ["SO1"], "course_outcomes": [],
                 "selected": True, "counted": True}]}
        scores = calculate_so_scores([_a("Alice", 8), _a("Bob", 6)])
        self.assertAlmostEqual(scores["SO1"]["mean"], 70.0, places=5)

    def test_program_outcomes_alias_accepted(self):
        """Scoring accepts program_outcomes field as well as abet_outcomes."""
        from src.tools.abet_scoring import score_student_outcomes
        c = {"id": "C1", "title": "T",
             "points_awarded": 7, "points_possible": 10,
             "program_outcomes": ["SO1"], "abet_outcomes": [],
             "course_outcomes": [],
             "selected": True, "counted": True}
        scores = score_student_outcomes([c], "program_outcomes")
        self.assertAlmostEqual(scores["SO1"], 70.0, places=5)

    def test_legacy_weights_title_keyed_fallback(self):
        """Title-keyed legacy weight must apply when ID lookup fails."""
        from src.tools.abet_scoring import score_student_outcomes
        c = {"id": "PS1_Q1", "title": "Q1 Runtime",
             "points_awarded": 8, "points_possible": 10,
             "program_outcomes": ["SO1"], "course_outcomes": [],
             "selected": True, "counted": True}
        weights = {"Q1 Runtime": {"SO1": 2.0}}
        scores = score_student_outcomes([c], "program_outcomes", weights=weights)
        self.assertAlmostEqual(scores["SO1"], 80.0, places=5)

    def test_id_keyed_weight_takes_priority_over_title(self):
        from src.tools.abet_scoring import score_student_outcomes
        c = {"id": "PS1_Q1", "title": "Q1 Runtime",
             "points_awarded": 8, "points_possible": 10,
             "program_outcomes": ["SO1"], "course_outcomes": [],
             "selected": True, "counted": True}
        weights = {"PS1_Q1": {"SO1": 1.0}, "Q1 Runtime": {"SO1": 99.0}}
        scores = score_student_outcomes([c], "program_outcomes", weights=weights)
        self.assertAlmostEqual(scores["SO1"], 80.0, places=5)


# ---------------------------------------------------------------------------
# Evidence policies
# ---------------------------------------------------------------------------

class TestEvidencePolicy(unittest.TestCase):

    def _assessment(self, awarded, possible, selected, counted):
        return {"student_name": "S", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": awarded, "points_possible": possible,
            "abet_outcomes": ["SO1"], "course_outcomes": [],
            "selected": selected, "counted": counted,
        }]}

    def test_counted_only_excludes_selected_not_counted(self):
        from src.tools.abet_scoring import calculate_so_scores, POLICY_COUNTED
        scores = calculate_so_scores(
            [self._assessment(10, 10, selected=True, counted=False)],
            policy=POLICY_COUNTED)
        self.assertNotIn("SO1", scores)

    def test_selected_policy_includes_selected_not_counted(self):
        from src.tools.abet_scoring import calculate_so_scores, POLICY_SELECTED
        scores = calculate_so_scores(
            [self._assessment(8, 10, selected=True, counted=False)],
            policy=POLICY_SELECTED)
        self.assertAlmostEqual(scores["SO1"]["mean"], 80.0, places=5)

    def test_all_policy_includes_everything(self):
        from src.tools.abet_scoring import calculate_so_scores, POLICY_ALL
        scores = calculate_so_scores(
            [self._assessment(5, 10, selected=False, counted=False)],
            policy=POLICY_ALL)
        self.assertAlmostEqual(scores["SO1"]["mean"], 50.0, places=5)


# ---------------------------------------------------------------------------
# Performance bands
# ---------------------------------------------------------------------------

class TestPerformanceBands(unittest.TestCase):

    def test_default_band_names(self):
        from src.tools.abet_scoring import DEFAULT_BANDS
        for name in ("excellent", "adequate", "needs_improvement", "inadequate"):
            self.assertIn(name, DEFAULT_BANDS)

    def test_76pct_is_adequate(self):
        from src.tools.abet_scoring import calculate_performance_bands
        bands = calculate_performance_bands([76.0])
        self.assertEqual(bands["adequate"]["count"], 1)

    def test_adequate_or_higher_rollup(self):
        from src.tools.abet_scoring import calculate_performance_bands
        bands = calculate_performance_bands([95.0, 80.0, 65.0])
        self.assertEqual(bands["adequate_or_higher"]["count"], 2)
        self.assertAlmostEqual(bands["adequate_or_higher"]["percentage"],
                               200 / 3, places=3)

    def test_proficient_or_higher_alias(self):
        from src.tools.abet_scoring import calculate_performance_bands
        bands = calculate_performance_bands([90.0])
        self.assertIn("proficient_or_higher", bands)

    def test_bonus_score_clamped_to_excellent(self):
        from src.tools.abet_scoring import calculate_performance_bands
        bands = calculate_performance_bands([110.0])
        self.assertEqual(bands["excellent"]["count"], 1)

    def test_negative_score_classified_as_inadequate(self):
        from src.tools.abet_scoring import calculate_performance_bands
        bands = calculate_performance_bands([-5.0])
        self.assertEqual(bands["inadequate"]["count"], 1)

    def test_check_targets_backfills_meets_target(self):
        from src.tools.abet_scoring import calculate_so_scores, check_targets
        scores = calculate_so_scores([{"student_name": "A", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 9, "points_possible": 10,
            "abet_outcomes": ["SO1"], "course_outcomes": [],
            "selected": True, "counted": True,
        }]}])
        check_targets(scores, target_pct=70.0)
        self.assertIn("meets_target", scores["SO1"])
        self.assertTrue(scores["SO1"]["meets_target"])

    def test_aggregate_contains_proficient_plus_pct(self):
        from src.tools.abet_scoring import calculate_so_scores
        scores = calculate_so_scores([{"student_name": "A", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 9, "points_possible": 10,
            "abet_outcomes": ["SO1"], "course_outcomes": [],
            "selected": True, "counted": True,
        }]}])
        self.assertIn("proficient_plus_pct", scores["SO1"])
        self.assertIn("band_counts", scores["SO1"])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def test_duplicate_ids_error(self):
        from src.tools.abet_validation import validate_rubric, ERROR
        rubric = {"criteria": [
            {"id": "SAME", "title": "Q1", "points": 5},
            {"id": "SAME", "title": "Q2", "points": 5},
        ]}
        issues = validate_rubric(rubric)
        self.assertIn("DUPLICATE_ID",
                      [i["code"] for i in issues if i["level"] == ERROR])

    def test_no_so_mapping_warning(self):
        from src.tools.abet_validation import validate_rubric, WARNING
        rubric = {"criteria": [
            {"id": "C1", "title": "Q1", "points": 5,
             "course_outcomes": [], "abet_outcomes": []},
        ]}
        issues = validate_rubric(rubric)
        self.assertIn("NO_SO_MAPPING",
                      [i["code"] for i in issues if i["level"] == WARNING])

    def test_unknown_outcome_ids_error(self):
        from src.tools.abet_validation import validate_rubric, ERROR
        rubric = {"criteria": [
            {"id": "C1", "title": "Q1", "points": 5,
             "course_outcomes": ["LO99"], "abet_outcomes": ["SO99"]},
        ]}
        issues = validate_rubric(rubric, known_lo_ids=["LO1"], known_so_ids=["SO1"])
        codes = [i["code"] for i in issues if i["level"] == ERROR]
        self.assertIn("UNKNOWN_LO", codes)
        self.assertIn("UNKNOWN_SO", codes)

    def test_valid_rubric_no_errors(self):
        from src.tools.abet_validation import validate_rubric, has_errors
        rubric = {"criteria": [
            {"id": "C1", "title": "Q1", "points": 5,
             "course_outcomes": ["LO1"], "abet_outcomes": ["SO1"],
             "assessment_tags": []},
        ]}
        issues = validate_rubric(rubric, ["LO1"], ["SO1"])
        self.assertFalse(has_errors(issues))

    def test_empty_criteria_error(self):
        from src.tools.abet_validation import validate_rubric, ERROR
        issues = validate_rubric({"criteria": []})
        self.assertTrue(any(i["level"] == ERROR for i in issues))

    def test_manual_duplicate_ids_preserved_and_flagged(self):
        """Duplicated manual IDs must not be rewritten — only flagged."""
        from src.core.rubric import _ensure_criterion_ids
        from src.tools.abet_validation import validate_rubric, ERROR
        rubric = {"criteria": [
            {"id": "SAME_ID", "title": "Q1", "points": 5,
             "course_outcomes": [], "abet_outcomes": [], "assessment_tags": []},
            {"id": "SAME_ID", "title": "Q2", "points": 5,
             "course_outcomes": [], "abet_outcomes": [], "assessment_tags": []},
        ]}
        _ensure_criterion_ids(rubric)
        ids = [c["id"] for c in rubric["criteria"]]
        self.assertEqual(ids, ["SAME_ID", "SAME_ID"])  # not rewritten
        issues = validate_rubric(rubric)
        self.assertIn("DUPLICATE_ID",
                      [i["code"] for i in issues if i["level"] == ERROR])


# ---------------------------------------------------------------------------
# Outcome profile
# ---------------------------------------------------------------------------

class TestOutcomeProfile(unittest.TestCase):

    def test_default_profile_loads(self):
        from src.core.outcome_profile import load_default_profile
        p = load_default_profile()
        self.assertEqual(p.profile_id, "cs2500_algorithms")
        self.assertIn("LO1", p.lo_ids())
        self.assertIn("SO1", p.po_ids())

    def test_runtime_keyword_maps_to_lo1(self):
        from src.core.outcome_profile import load_default_profile
        p = load_default_profile()
        self.assertIn("LO1", p.infer_los_from_title("Question 2 - Runtime Analysis"))

    def test_proof_keyword_maps_to_lo4(self):
        from src.core.outcome_profile import load_default_profile
        p = load_default_profile()
        self.assertIn("LO4", p.infer_los_from_title("Correctness proof by induction"))

    def test_lo1_derives_so1_and_so6(self):
        from src.core.outcome_profile import load_default_profile
        p = load_default_profile()
        sos = p.derive_abet_from_los(["LO1"])
        self.assertIn("SO1", sos)
        self.assertIn("SO6", sos)

    def test_lo7_derives_so3(self):
        from src.core.outcome_profile import load_default_profile
        p = load_default_profile()
        self.assertIn("SO3", p.derive_abet_from_los(["LO7"]))

    def test_generic_template_loads(self):
        from src.core.outcome_profile import load_generic_template
        p = load_generic_template()
        self.assertEqual(p.profile_id, "generic_course")
        self.assertIn("LO1", p.lo_ids())

    def test_list_profiles(self):
        from src.core.outcome_profile import list_available_profiles
        profiles = list_available_profiles()
        self.assertIn("cs2500_algorithms", profiles)
        self.assertIn("generic_course", profiles)

    def test_legacy_abet_outcomes_key_accepted(self):
        from src.core.outcome_profile import create_profile_from_dict
        old_style = {
            "schema_version": "2.0",
            "profile_id": "old_style",
            "course_outcomes": {"LO1": "Old LO"},
            "abet_outcomes":   {"SO1": "Old SO"},
            "default_lo_to_abet": {"LO1": ["SO1"]},
            "keyword_to_lo": {},
        }
        p = create_profile_from_dict(old_style)
        self.assertIn("SO1", p.program_outcomes)
        self.assertEqual(p.program_for_lo("LO1"), ["SO1"])


class TestProfileGeneralisation(unittest.TestCase):
    """Scoring + profiles work for non-CS2500 courses."""

    def _ir_profile(self):
        from src.core.outcome_profile import create_profile_from_dict
        return create_profile_from_dict({
            "schema_version": "2.0",
            "profile_id": "cs5001_information_retrieval",
            "course_code": "CS 5001",
            "course_name": "Information Retrieval",
            "course_outcomes": {
                "LO1": "Indexing.", "LO2": "Retrieval models.", "LO3": "Evaluation."},
            "program_outcomes": {
                "SO1": "Analyze.", "SO2": "Design.", "SO3": "Communicate."},
            "default_course_to_program": {
                "LO1": ["SO1", "SO2"], "LO2": ["SO1"], "LO3": ["SO1", "SO3"]},
            "performance_bands": {
                "excellent": [90.0, 100.0], "adequate": [75.0, 89.99],
                "needs_improvement": [40.0, 74.99], "inadequate": [0.0, 39.99]},
            "passing_bands": ["excellent", "adequate"],
            "target_percentage": 75.0,
            "keyword_to_course_outcome": {
                "LO1": ["index", "tokenization"], "LO2": ["tf-idf", "bm25"],
                "LO3": ["map", "ndcg"]},
        })

    def test_crosswalk(self):
        p = self._ir_profile()
        pos = p.derive_program_from_los(["LO3"])
        self.assertIn("SO1", pos)
        self.assertIn("SO3", pos)

    def test_keyword_inference(self):
        p = self._ir_profile()
        self.assertIn("LO1", p.infer_los_from_title("Implement an inverted index"))

    def test_profile_bands_flow_to_scoring(self):
        from src.tools.abet_scoring import calculate_so_scores
        p = self._ir_profile()
        assessments = [{"student_name": "Alice", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 7.6, "points_possible": 10,
            "program_outcomes": ["SO1"], "course_outcomes": [],
            "selected": True, "counted": True,
        }]}]
        scores = calculate_so_scores(assessments, profile=p)
        self.assertEqual(scores["SO1"]["band_counts"]["adequate"]["count"], 1)

    def test_profile_target_in_check_targets(self):
        from src.tools.abet_scoring import calculate_so_scores, check_targets
        p = self._ir_profile()
        assessments = [{"student_name": "Alice", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 7.2, "points_possible": 10,
            "program_outcomes": ["SO1"], "course_outcomes": [],
            "selected": True, "counted": True,
        }]}]
        scores = calculate_so_scores(assessments, profile=p)
        check_targets(scores, target_pct=70.0, profile=p)
        # 72% < 75% (profile target) → does not meet
        self.assertFalse(scores["SO1"]["meets_target"])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
