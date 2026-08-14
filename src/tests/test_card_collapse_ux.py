"""Regression tests for prominent collapsible-section controls."""

from pathlib import Path
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = (_REPO_ROOT / "src" / "ui" / "widgets" / "card.py").read_text(encoding="utf-8")


class TestCardCollapseUx(unittest.TestCase):

    def test_collapsed_card_uses_explicit_show_label_not_tiny_glyph(self):
        self.assertIn('self.collapse_button.setText("Show ▼")', _SOURCE)
        self.assertIn('self.collapse_button.setToolTip(f"Show {self.title}")', _SOURCE)

    def test_expanded_card_uses_explicit_hide_label(self):
        self.assertIn('self.collapse_button.setText("Hide ▲")', _SOURCE)
        self.assertIn('self.collapse_button.setToolTip(f"Hide {self.title}")', _SOURCE)

    def test_collapse_button_has_visible_bordered_hit_target(self):
        self.assertIn("min-width: 64px", _SOURCE)
        self.assertIn("border: 1px solid #D9DEE7", _SOURCE)
        self.assertIn("font-weight: 600", _SOURCE)

    def test_card_emits_collapse_state_for_layout_resizing(self):
        self.assertIn("collapsed_changed = pyqtSignal(bool)", _SOURCE)
        self.assertIn("self.collapsed_changed.emit(self._collapsed)", _SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
