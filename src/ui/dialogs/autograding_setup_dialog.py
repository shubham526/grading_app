"""Instructor autograder bundle/runtime configuration dialog for v2.3.3."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.autograding.execution.docker_pytest_backend import DEFAULT_DOCKER_PYTEST_IMAGE
from src.autograding.service import AutogradingService


class AutogradingSetupDialog(QDialog):
    def __init__(
        self,
        service: AutogradingService,
        assessment_id: str,
        *,
        selected_bundle_id: Optional[str] = None,
        runtime_image: str = DEFAULT_DOCKER_PYTEST_IMAGE,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(service, AutogradingService):
            raise TypeError("service must be AutogradingService")
        self.service = service
        self.assessment_id = str(assessment_id or "").strip()
        if not self.assessment_id:
            raise ValueError("assessment_id is required")
        self._requested_bundle_id = str(selected_bundle_id or "").strip() or None
        self._build_ui(runtime_image)
        self.refresh_bundles()

    def _build_ui(self, runtime_image: str) -> None:
        self.setObjectName("autogradingSetupDialog")
        self.setWindowTitle("Programming Autograding — Configure")
        self.resize(900, 560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        heading = QLabel("Programming Autograding Configuration", self)
        heading.setProperty("labelType", "heading")
        outer.addWidget(heading)
        context = QLabel("Assessment: %s" % self.assessment_id, self)
        context.setStyleSheet("color: #667085;")
        outer.addWidget(context)

        note = QLabel(
            "Import or select an immutable instructor test bundle. The runtime image must already "
            "exist locally; the grading app never auto-pulls or auto-builds execution images.",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #667085;")
        outer.addWidget(note)

        runtime_row = QHBoxLayout()
        runtime_row.addWidget(QLabel("Docker pytest image:", self))
        self.runtime_image_edit = QLineEdit(str(runtime_image or DEFAULT_DOCKER_PYTEST_IMAGE), self)
        self.runtime_image_edit.setObjectName("autogradingRuntimeImageEdit")
        runtime_row.addWidget(self.runtime_image_edit, 1)
        self.test_runtime_button = QPushButton("Check Runtime", self)
        self.test_runtime_button.clicked.connect(self.check_runtime)
        runtime_row.addWidget(self.test_runtime_button)
        outer.addLayout(runtime_row)

        self.runtime_status = QLabel("Runtime not checked.", self)
        self.runtime_status.setObjectName("autogradingRuntimeStatus")
        self.runtime_status.setWordWrap(True)
        outer.addWidget(self.runtime_status)

        actions = QHBoxLayout()
        self.import_button = QPushButton("Import Test Bundle…", self)
        self.import_button.clicked.connect(self.import_bundle)
        actions.addWidget(self.import_button)
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.refresh_bundles)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        outer.addLayout(actions)

        self.table = QTableWidget(0, 5, self)
        self.table.setObjectName("autogradingBundleTable")
        self.table.setHorizontalHeaderLabels(
            ["Version", "Bundle ID", "Imported", "Bundle SHA-256", "Config SHA-256"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.use_button = QPushButton("Use Selected Bundle", self)
        self.use_button.setProperty("buttonRole", "primary")
        self.use_button.clicked.connect(self.accept)
        footer.addWidget(self.use_button)
        outer.addLayout(footer)

    @property
    def runtime_image(self) -> str:
        return self.runtime_image_edit.text().strip()

    @property
    def selected_bundle_id(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 1)
        return None if item is None else str(item.data(Qt.UserRole) or item.text()).strip() or None

    def refresh_bundles(self) -> None:
        try:
            refs = list(self.service.list_bundles(self.assessment_id))
        except Exception as exc:
            QMessageBox.critical(self, "Autograding Bundles", str(exc))
            refs = []
        self.table.setRowCount(len(refs))
        requested_row = None
        for row, ref in enumerate(refs):
            version = ref.display_version or "—"
            self.table.setItem(row, 0, QTableWidgetItem(version))
            bundle_item = QTableWidgetItem(ref.bundle_id)
            bundle_item.setData(Qt.UserRole, ref.bundle_id)
            self.table.setItem(row, 1, bundle_item)
            self.table.setItem(row, 2, QTableWidgetItem(ref.imported_at))
            bsha = QTableWidgetItem(ref.bundle_sha256[:16] + "…")
            bsha.setToolTip(ref.bundle_sha256)
            self.table.setItem(row, 3, bsha)
            csha = QTableWidgetItem(ref.config_sha256[:16] + "…")
            csha.setToolTip(ref.config_sha256)
            self.table.setItem(row, 4, csha)
            if self._requested_bundle_id == ref.bundle_id:
                requested_row = row
        if refs:
            self.table.selectRow(requested_row if requested_row is not None else len(refs) - 1)
        self._update_buttons()

    def import_bundle(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Autograder Bundle Folder",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not directory:
            return
        try:
            result = self.service.import_bundle(self.assessment_id, directory)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to Import Test Bundle", str(exc))
            return
        self._requested_bundle_id = result.bundle.reference.bundle_id
        self.refresh_bundles()
        QMessageBox.information(
            self,
            "Test Bundle Ready",
            "Imported a new immutable bundle."
            if result.created
            else "This exact bundle was already stored; the existing immutable bundle was reused.",
        )

    def check_runtime(self) -> None:
        if not self.runtime_image:
            QMessageBox.warning(self, "Runtime Image", "Enter a Docker runtime image first.")
            return
        self.test_runtime_button.setEnabled(False)
        self.runtime_status.setText("Checking Docker/pytest runtime…")
        try:
            availability = self.service.runtime_availability(self.runtime_image)
        except Exception as exc:
            self.runtime_status.setText("Unavailable: %s" % exc)
        else:
            if availability.available:
                self.runtime_status.setText("Available — Docker and the pinned pytest runtime are ready.")
            else:
                self.runtime_status.setText("Unavailable: %s" % (availability.reason or "unknown reason"))
        finally:
            self.test_runtime_button.setEnabled(True)

    def _update_buttons(self) -> None:
        self.use_button.setEnabled(bool(self.selected_bundle_id and self.runtime_image))

    def accept(self) -> None:
        if not self.selected_bundle_id:
            QMessageBox.warning(self, "Select Bundle", "Select an autograder bundle first.")
            return
        if not self.runtime_image:
            QMessageBox.warning(self, "Runtime Image", "Enter a Docker runtime image first.")
            return
        super().accept()


__all__ = ["AutogradingSetupDialog"]
