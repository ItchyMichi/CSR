import sys
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QStatusBar,
    QTableWidget, QTableWidgetItem, QComboBox, QHeaderView, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import Qt


class DeckFieldMappingDialog(QDialog):
    def __init__(self, anki_fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map Anki Fields to App Fields")
        self.setMinimumSize(940, 560)

        # Example local fields
        self.local_fields = ["native word", "native sentence", "translated word", "translated sentence", "sentence audio", "word audio", "image", "pos", "reading"]

        self.anki_fields = anki_fields  # A list of field names from the Anki deck

        main_layout = QVBoxLayout(self)

        # Info label
        info_label = QLabel("Please map the Anki deck fields to the local fields used by the application.")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)

        # Table to map fields
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Anki Field", "App Field Mapping"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setRowCount(len(self.anki_fields))

        for row, field_name in enumerate(self.anki_fields):
            # Anki field name cell
            field_item = QTableWidgetItem(field_name)
            field_item.setFlags(field_item.flags() ^ Qt.ItemIsEditable)  # not editable
            self.table.setItem(row, 0, field_item)

            # ComboBox for mapping
            combo = QComboBox()
            combo.addItems(["(Ignore)"] + self.local_fields)  # Allow ignoring a field if not needed
            self.table.setCellWidget(row, 1, combo)

        main_layout.addWidget(self.table)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addSpacerItem(QSpacerItem(40,20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        btn_confirm = QPushButton("Confirm")
        btn_cancel = QPushButton("Cancel")
        btn_confirm.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_confirm)
        button_layout.addWidget(btn_cancel)

        main_layout.addLayout(button_layout)

        # Status bar
        self.status_bar = QStatusBar()
        main_layout.addWidget(self.status_bar)
        self.status_bar.showMessage("Select field mappings, then click Confirm.")

    def get_mappings(self):
        """
        Returns a dict of {anki_field_name: local_field_name or None} based on user selection.
        If user chooses "(Ignore)", local_field_name will be None.
        """
        mappings = {}
        for row in range(self.table.rowCount()):
            anki_field = self.table.item(row, 0).text()
            combo = self.table.cellWidget(row, 1)
            selected = combo.currentText()
            if selected == "(Ignore)":
                mappings[anki_field] = None
            else:
                mappings[anki_field] = selected
        return mappings