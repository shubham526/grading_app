from PyQt5.QtWidgets import QTextEdit, QVBoxLayout, QWidget, QSplitter
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt


class MarkdownMathEditor(QWidget):
    """Text editor with Markdown and LaTeX math support"""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create a splitter for editor and preview
        splitter = QSplitter(Qt.Vertical)

        # Regular text editor for input
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Enter feedback using Markdown. Use $...$ for inline math or $$...$$ for display math.")
        self.editor.textChanged.connect(self.update_preview)
        splitter.addWidget(self.editor)

        # Web view for rendered preview
        self.preview = QWebEngineView()
        splitter.addWidget(self.preview)

        # Set initial sizes (editor gets more space)
        splitter.setSizes([200, 100])

        layout.addWidget(splitter)

        # Initialize with Markdown-it and KaTeX
        self.template = (
            "<!DOCTYPE html>"
            "<html>"
            "<head>"
            "    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/katex.min.css\">"
            "    <script src=\"https://cdn.jsdelivr.net/npm/markdown-it@13.0.1/dist/markdown-it.min.js\"></script>"
            "    <script src=\"https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/katex.min.js\"></script>"
            "    <script src=\"https://cdn.jsdelivr.net/npm/markdown-it-texmath@1.0.0/texmath.min.js\"></script>"
            "    <style>"
            "        body { font-family: sans-serif; padding: 10px; margin: 0; }"
            "        code { background: #f0f0f0; padding: 2px 4px; border-radius: 4px; }"
            "        pre { background: #f0f0f0; padding: 10px; border-radius: 4px; }"
            "        .math-block { margin: 10px 0; }"
            "    </style>"
            "</head>"
            "<body>"
            "    <div id=\"content\"></div>"
            "    <script>"
            "        // Setup markdown-it with KaTeX support"
            "        const md = window.markdownit();"
            "        const tm = window.texmath;"
            "        const kt = window.katex;"
            "        md.use(tm, { engine: kt, delimiters: ['dollars', 'brackets'] });"
            "        "
            "        // Render the content"
            "        document.getElementById('content').innerHTML = md.render(`{}`);"
            "    </script>"
            "</body>"
            "</html>"
        )
        self.update_preview()

    def update_preview(self):
        """Update the preview with rendered markdown and math"""
        content = self.editor.toPlainText()
        # Escape backticks and curly braces for JS template string
        content = content.replace('\\', '\\\\').replace('`', '\\`').replace('{', '\\{').replace('}', '\\}')
        html = self.template.format(content)
        self.preview.setHtml(html)

    def get_text(self):
        """Get the raw markdown text with LaTeX math expressions"""
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
        self.update_preview()