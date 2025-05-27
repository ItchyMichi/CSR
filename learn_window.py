import sys
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QSpinBox, QLabel,
    QStatusBar, QFormLayout, QDialogButtonBox
)
from PyQt5.QtCore import Qt

# We'll import the run_minigame function from a separate module that uses PyGame
from minigame_pygame import run_minigame

class LearnWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Learn - Mini Games")
        self.setMinimumSize(400, 200)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Form layout for game configuration
        form_layout = QFormLayout()

        # Minigame selection
        self.minigame_combo = QComboBox()
        # For now, only one minigame
        self.minigame_combo.addItem("Image Selection Game")
        form_layout.addRow("Minigame:", self.minigame_combo)

        # Difficulty selection
        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItems(["Easy", "Medium", "Hard"])
        form_layout.addRow("Difficulty:", self.difficulty_combo)

        # Time limit selection
        self.time_limit_spin = QSpinBox()
        self.time_limit_spin.setRange(10, 300)  # 10 to 300 seconds
        self.time_limit_spin.setValue(60)  # default 60 seconds
        form_layout.addRow("Time Limit (s):", self.time_limit_spin)

        main_layout.addLayout(form_layout)

        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.start_game)
        button_box.rejected.connect(self.close)
        main_layout.addWidget(button_box)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Configure your minigame and click OK to start.")

    def start_game(self):
        minigame = self.minigame_combo.currentText()
        difficulty = self.difficulty_combo.currentText()
        time_limit = self.time_limit_spin.value()

        # Run the PyGame minigame in a separate call
        # This will block until the game is done in this simplified example.
        run_minigame(minigame, difficulty, time_limit)
        self.status_bar.showMessage("Game session ended.")
