import os
import json

from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QSpacerItem, QSizePolicy, QTableView, \
    QHeaderView, QPushButton, QTabWidget, QWidget, QStatusBar, QRadioButton, QButtonGroup, QMainWindow


class StudyPlanWindow(QMainWindow):
    def __init__(self, parent=None, db_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Study Plan")
        self.setMinimumSize(800, 600)

        # Store reference to DB manager if you need it to query 'texts'
        self.db_manager = db_manager  # <== pass from parent for DB lookups

        # Central widget with tabs
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Create the Study Plan tab
        self.study_plan_tab = QWidget()
        self.tab_widget.addTab(self.study_plan_tab, "Study Plan")

        # Create the Sentences tab
        self.sentences_tab = QWidget()
        self.tab_widget.addTab(self.sentences_tab, "Sentences")

        # Initialize the tabs
        self.init_study_plan_tab()
        self.init_sentences_tab()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def init_study_plan_tab(self):
        layout = QVBoxLayout(self.study_plan_tab)

        # -- For brevity, these top controls remain the same --
        top_controls_layout = QHBoxLayout()
        self.daily_radio = QRadioButton("Daily Plan")
        self.daily_radio.setChecked(True)
        self.long_term_radio = QRadioButton("Long-Term Plan")

        plan_group = QButtonGroup(self)
        plan_group.addButton(self.daily_radio)
        plan_group.addButton(self.long_term_radio)
        plan_group.buttonClicked.connect(self.update_task_view)

        top_controls_layout.addWidget(QLabel("Select Plan Type:"))
        top_controls_layout.addWidget(self.daily_radio)
        top_controls_layout.addWidget(self.long_term_radio)
        top_controls_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        layout.addLayout(top_controls_layout)

        # -- Here's our QTableView for the Plan's text files (instead of dummy tasks) --
        self.texts_view = QTableView()
        self.texts_view.setSelectionBehavior(QTableView.SelectRows)
        self.texts_view.setAlternatingRowColors(True)

        # Model for text files
        self.texts_model = QStandardItemModel()
        # Display just "File Name" for simplicity, or you can add more columns as needed
        self.texts_model.setHorizontalHeaderLabels(["File Name"])

        # Load text file names from current_session.json
        self.load_plan_texts()

        self.texts_view.setModel(self.texts_model)
        self.texts_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.texts_view)

        # Bottom submit button (just a dummy to match your style)
        bottom_layout = QHBoxLayout()
        submit_button = QPushButton("Submit Completed Tasks")
        submit_button.clicked.connect(self.submit_tasks_dummy)

        bottom_layout.addWidget(submit_button)
        bottom_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(bottom_layout)

    def load_plan_texts(self):
        """
        Reads current_session.json, gets text_ids, looks up each in the DB (texts table),
        extracts the file name from 'source', and populates the self.texts_model.
        """
        # Path to the JSON; adjust as needed:
        plan_path = os.path.join("study_plans", "current_session.json")
        if not os.path.exists(plan_path):
            self.status_bar.showMessage("No current_session.json found.")
            return

        # Load the JSON
        with open(plan_path, "r", encoding="utf-8") as f:
            plan_data = json.load(f)

        # Get the list of text_ids
        text_ids = plan_data.get("text_ids", [])
        if not text_ids:
            self.status_bar.showMessage("No text_ids in current_session.json.")
            return

        # Clear existing rows
        self.texts_model.removeRows(0, self.texts_model.rowCount())

        # For each text_id, query the DB for the source, then extract filename
        for t_id in text_ids:
            source = self.lookup_text_source(t_id)
            if not source:
                # If not found in DB, skip or add a placeholder
                row_items = [QStandardItem("[Missing or not found]")]
            else:
                # Just the file name
                filename = os.path.basename(source)
                row_items = [QStandardItem(filename)]

            self.texts_model.appendRow(row_items)

    def lookup_text_source(self, text_id):
        """
        Query the DB's 'texts' table for the given text_id.
        Return the 'source' column or None if not found.
        """
        if not self.db_manager:
            return None

        cur = self.db_manager._conn.cursor()
        cur.execute("SELECT source FROM texts WHERE text_id = ?", (text_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    # -------------------------------------------------------------------------
    # The rest of the code remains largely as in your snippet...
    # -------------------------------------------------------------------------

    def init_sentences_tab(self):
        layout = QVBoxLayout(self.sentences_tab)
        filter_layout = QHBoxLayout()
        self.search_line_sentences = QLineEdit()
        self.search_line_sentences.setPlaceholderText("Search sentences...")
        self.search_line_sentences.textChanged.connect(self.update_sentence_filter)
        filter_layout.addWidget(QLabel("Search:"))
        filter_layout.addWidget(self.search_line_sentences)
        filter_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(filter_layout)

        self.sentences_view = QTableView()
        self.sentences_view.setSelectionBehavior(QTableView.SelectRows)
        self.sentences_view.setAlternatingRowColors(True)
        self.sentences_model = QStandardItemModel()
        self.sentences_model.setHorizontalHeaderLabels(["Sentence ID", "Content", "Text ID", "Unknown Words Count"])
        dummy_sentences = [
            [101, "これはペンです。", 1, 0],
            [102, "猫がソファーで寝ている。", 1, 1],
            [103, "明日は学校に行きます。", 2, 2]
        ]
        for row_data in dummy_sentences:
            row_items = [QStandardItem(str(x)) for x in row_data]
            self.sentences_model.appendRow(row_items)
        self.sentences_view.setModel(self.sentences_model)
        self.sentences_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.sentences_view)

    def load_tasks(self, tasks_data):
        # Not used now, but if you still have daily/longterm tasks
        pass

    def update_task_view(self):
        # Example stub
        self.status_bar.showMessage("Task view updated (dummy).")

    def submit_tasks_dummy(self):
        self.status_bar.showMessage("Tasks submitted (dummy).")

    def update_sentence_filter(self):
        self.status_bar.showMessage("Sentence filter updated (dummy).")
