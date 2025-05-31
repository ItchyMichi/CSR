from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QStatusBar, QScrollArea, QFrame, QSpacerItem, QSizePolicy, QCheckBox
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
import configparser
import os
import re

class ExploreWordsWindow(QMainWindow):
    def __init__(self, parent=None, db_manager=None, sentence_id=None, sentence_text=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.sentence_id = sentence_id
        self.sentence_text = sentence_text
        self.setWindowTitle("Explore New Words")
        self.setMinimumSize(600, 400)

        # Load config to find media path
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.anki_media_path = self.config.get("PATHS", "anki_media_path", fallback="")
        self.tmdb_api_key = self.config['DEFAULT'].get('TMDB_API_Key', '')

        # Audio player
        self.player = QMediaPlayer()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Sentence indicator
        self.sentence_indicator = QLabel("Random Sentence")
        self.sentence_indicator.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.sentence_indicator)

        # Image label
        self.image_label = QLabel("[No Image]")
        self.image_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.image_label)

        self.sentence_label = QLabel(self.sentence_text if self.sentence_text else "")
        self.sentence_label.setAlignment(Qt.AlignCenter)
        self.sentence_label.setWordWrap(True)

        # Increase font size for sentence text
        sentence_font = self.sentence_label.font()
        sentence_font.setPointSize(sentence_font.pointSize() * 2)
        self.sentence_label.setFont(sentence_font)
        main_layout.addWidget(self.sentence_label)

        audio_layout = QHBoxLayout()
        audio_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.btn_replay_audio = QPushButton("Replay Audio")
        self.btn_replay_audio.clicked.connect(self.replay_audio)
        audio_layout.addWidget(self.btn_replay_audio)
        audio_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        main_layout.addLayout(audio_layout)

        self.words_scroll = QScrollArea()
        self.words_scroll.setWidgetResizable(True)
        words_container = QWidget()
        self.words_layout = QHBoxLayout(words_container)
        self.words_layout.setAlignment(Qt.AlignCenter)
        self.words_scroll.setWidget(words_container)
        main_layout.addWidget(self.words_scroll)

        bottom_layout = QHBoxLayout()
        bottom_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.btn_submit = QPushButton("Next Sentence")
        self.btn_submit.clicked.connect(self.submit_sentence)
        bottom_layout.addWidget(self.btn_submit)
        bottom_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        main_layout.addLayout(bottom_layout)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self.checkboxes = {}  # dict_form_id -> checkbox
        self.current_audio_file = None  # store current audio file path

        # Load initial sentence or a random one if not provided
        if self.sentence_id is not None and self.sentence_text is not None:
            self.load_media()
            self.load_surface_forms()
        else:
            self.load_random_sentence()

    def load_random_sentence(self):
        sentence_data = self.db_manager.get_random_sentence()
        if not sentence_data:
            self.status_bar.showMessage("No sentences found in the database.")
            self.clear_sentence_display()
            return

        self.sentence_id, self.sentence_text = sentence_data
        self.sentence_label.setText(self.sentence_text)
        self.load_media()
        self.load_surface_forms()

    def load_media(self):
        # Fetch card associated with this sentence to get audio/image fields
        card_data = self.db_manager.get_card_by_sentence_id(self.sentence_id)
        if not card_data:
            # If no card found, clear
            self.image_label.setText("[No Image]")
            self.current_audio_file = None
            return

        sentence_audio, image_html = card_data

        # Parse audio file from [sound:filename.mp3]
        audio_file = None
        if sentence_audio:
            # Typically: [sound:filename.mp3]
            match = re.search(r'\[sound:(.*?)\]', sentence_audio)
            if match:
                audio_filename = match.group(1)
                audio_file = os.path.join(self.anki_media_path, audio_filename)
                if not os.path.exists(audio_file):
                    self.status_bar.showMessage(f"Audio file not found: {audio_file}")
                    audio_file = None
            else:
                self.status_bar.showMessage("No valid sound tag found.")

        self.current_audio_file = audio_file

        # Parse image file from <img src="filename.png">
        image_file = None
        if image_html:
            match = re.search(r'<img\s+src="([^"]+)"', image_html)
            if match:
                image_filename = match.group(1)
                image_file = os.path.join(self.anki_media_path, image_filename)
                if not os.path.exists(image_file):
                    self.status_bar.showMessage(f"Image file not found: {image_file}")
                    image_file = None

        if image_file:
            pixmap = QPixmap(image_file)
            if not pixmap.isNull():
                scaled_pix = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled_pix)
            else:
                self.image_label.setText("[Image not found or invalid]")
        else:
            self.image_label.setText("[No Image]")

    def load_surface_forms(self):
        if not self.sentence_id:
            return

        forms = self.db_manager.get_surface_forms_for_sentence(self.sentence_id)

        # Clear previous word widgets
        for i in reversed(range(self.words_layout.count())):
            item = self.words_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        self.checkboxes.clear()

        # Font for words
        word_font = QFont()
        default_point_size = word_font.pointSize()
        word_font.setPointSize(default_point_size * 2)

        if not forms:
            no_words_label = QLabel("No words found in this sentence.")
            no_words_label.setAlignment(Qt.AlignCenter)
            no_words_label.setFont(word_font)
            self.words_layout.addWidget(no_words_label)
            return

        # Create widgets for each surface form
        for (sf_id, sf_text, df_id, df_base, df_known) in forms:
            word_container = QWidget()
            word_layout = QVBoxLayout(word_container)

            word_label = QLabel(sf_text)
            word_label.setAlignment(Qt.AlignCenter)
            word_label.setFont(word_font)

            dict_form_label = QLabel(f"({df_base})")
            dict_form_label.setAlignment(Qt.AlignCenter)
            dict_form_label.setFont(word_font)

            word_checkbox = QCheckBox("Known?")
            word_checkbox.setFont(word_font)
            word_checkbox.setChecked(bool(df_known))
            word_checkbox.stateChanged.connect(lambda state, d_id=df_id: self.on_checkbox_toggled(d_id, state))

            word_layout.addWidget(word_label)
            word_layout.addWidget(dict_form_label)
            word_layout.addWidget(word_checkbox)
            word_layout.setAlignment(Qt.AlignHCenter)
            self.words_layout.addWidget(word_container)

            self.checkboxes[df_id] = word_checkbox

    def on_checkbox_toggled(self, dict_form_id, state):
        known = (state == Qt.Checked)
        self.db_manager.set_dictionary_form_known(dict_form_id, known)
        self.db_manager.update_unknown_counts_for_dict_form(dict_form_id)
        self.status_bar.showMessage("Dictionary form known status updated.")

    def replay_audio(self):
        if self.current_audio_file and os.path.exists(self.current_audio_file):
            self.status_bar.showMessage("Playing audio...")
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.current_audio_file)))
            self.player.play()
        else:
            self.status_bar.showMessage("No audio file available to play.")

    def submit_sentence(self):
        # Load a new random sentence
        self.load_random_sentence()
        self.status_bar.showMessage("Loaded a new random sentence.")

    def clear_sentence_display(self):
        self.sentence_label.setText("No sentences available")
        # Clear words area
        for i in reversed(range(self.words_layout.count())):
            item = self.words_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()
