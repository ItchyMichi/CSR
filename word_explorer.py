from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QGridLayout, QStatusBar, QTableView, QComboBox, QLineEdit,
    QHeaderView, QFrame, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItemModel, QStandardItem

class WordExplorerWindow(QMainWindow):
    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager  # Make sure to pass a db_manager instance here
        self.setWindowTitle("Word Explorer")
        self.setMinimumSize(800, 600)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top filter bar
        filter_layout = QHBoxLayout()

        # Combo box to select view mode: All, Known, Unknown
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["All Words", "Known Words", "Unknown Words"])
        self.view_mode_combo.currentIndexChanged.connect(self.update_filter)

        # Combo box to select a tag filter (dummy tags)
        self.tag_filter_combo = QComboBox()
        self.tag_filter_combo.addItem("All Tags")
        self.tag_filter_combo.addItem("Tag: Known")
        self.tag_filter_combo.addItem("Tag: High Frequency")
        self.tag_filter_combo.addItem("Tag: Custom")
        self.tag_filter_combo.currentIndexChanged.connect(self.update_filter)

        # Line edit for searching words
        self.search_line = QLineEdit()
        self.search_line.setPlaceholderText("Search by lemma or reading...")
        self.search_line.textChanged.connect(self.update_filter)

        filter_layout.addWidget(QLabel("View:"))
        filter_layout.addWidget(self.view_mode_combo)
        filter_layout.addWidget(QLabel("Filter by Tag:"))
        filter_layout.addWidget(self.tag_filter_combo)
        filter_layout.addWidget(QLabel("Search:"))
        filter_layout.addWidget(self.search_line)

        # Add a spacer
        filter_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        main_layout.addLayout(filter_layout)

        # The table view for words
        self.table_view = QTableView()
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setAlternatingRowColors(True)

        # Set up a dummy model for now. In real code, populate from DB.
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Word ID", "Lemma", "Reading", "POS", "Known", "Tags", "Card ID"])

        # Insert dummy data (in real scenario, load from DB)
        dummy_data = [
            [1, "猫", "ねこ", "Noun", "Yes", "known;N5", 1001],
            [2, "犬", "いぬ", "Noun", "No", "N5", 1002],
            [3, "走る", "はしる", "Verb", "No", "high_frequency", 1003],
            [4, "食べる", "たべる", "Verb", "Yes", "known;high_frequency", 1004]
        ]

        for row_data in dummy_data:
            row_items = [QStandardItem(str(x)) for x in row_data]
            self.model.appendRow(row_items)

        self.table_view.setModel(self.model)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        main_layout.addWidget(self.table_view)

        # Bottom actions
        actions_layout = QHBoxLayout()

        # Explore New Words button
        btn_explore_new = QPushButton("Explore New Words")
        btn_explore_new.clicked.connect(self.explore_new_words)

        # Apply Tag button
        btn_apply_tag = QPushButton("Apply Tag to Selected")
        btn_apply_tag.clicked.connect(self.apply_tag_dummy)

        # Add Media button
        btn_add_media = QPushButton("Add Media to Selected")
        btn_add_media.clicked.connect(self.add_media_dummy)

        actions_layout.addWidget(btn_explore_new)
        actions_layout.addWidget(btn_apply_tag)
        actions_layout.addWidget(btn_add_media)
        actions_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        main_layout.addLayout(actions_layout)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def update_filter(self):
        # Dummy filter method
        self.status_bar.showMessage("Filter updated (dummy).")

    def explore_new_words(self):
        sentence_data = self.db_manager.get_random_sentence()
        if not sentence_data:
            self.status_bar.showMessage("No sentences found in the database.")
            return

        sentence_id, sentence_text = sentence_data
        from explore_words_window import ExploreWordsWindow
        self.explore_window = ExploreWordsWindow(self, db_manager=self.db_manager, sentence_id=sentence_id,
                                                 sentence_text=sentence_text)
        self.explore_window.show()
        self.status_bar.showMessage("Explore New Words window opened with a random sentence.")

    def apply_tag_dummy(self):
        selected_indexes = self.table_view.selectionModel().selectedRows()
        if not selected_indexes:
            self.status_bar.showMessage("No words selected to tag.")
            return
        self.status_bar.showMessage("Apply Tag to selected words (dummy).")

    def add_media_dummy(self):
        selected_indexes = self.table_view.selectionModel().selectedRows()
        if not selected_indexes:
            self.status_bar.showMessage("No words selected for media addition.")
            return
        self.status_bar.showMessage("Add Media to selected words (dummy).")