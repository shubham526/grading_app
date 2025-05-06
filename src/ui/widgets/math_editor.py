from PyQt5.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class MarkdownMathEditor(QWidget):
    """Simple text editor that supports math input"""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Regular text editor for input
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Enter feedback....")
        layout.addWidget(self.editor)

    def get_text(self):
        """Get the raw text"""
        return self.editor.toPlainText()

    def set_text(self, text):
        """Set the text content"""
        self.editor.setPlainText(text)

    def toPlainText(self):
        """Compatibility with QTextEdit interface"""
        return self.get_text()

    def setPlainText(self, text):
        """Compatibility with QTextEdit interface"""
        self.set_text(text)

    def clear(self):
        """Compatibility with QTextEdit interface"""
        self.editor.clear()