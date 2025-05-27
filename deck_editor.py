import traceback
import logging
import os
import re
import uuid
import base64
import configparser
import requests

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox,
    QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit, QPushButton,
    QLabel, QComboBox, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize, QUrl
from PyQt5.QtGui import QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
import openai
from google.cloud import texttospeech

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Deck Editor")

class DeckEditorWindow(QWidget):
    def __init__(self, db_manager=None, anki=None, parent=None):
        super().__init__(parent)
        logger.info("Initializing DeckEditorWindow.__init__")

        # Force this widget to be a top-level window:
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)

        self.db = db_manager  # must implement update_card_audio, update_card_image, update_anki_note_field, etc.
        self.anki = anki      # must implement .invoke(...) or similar

        self.setWindowTitle("Deck Editor")

        # Load config to get anki_media_path, OpenAI key, Google TTS key, etc.
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.anki_media_path = self.config.get("PATHS", "anki_media_path", fallback="")
        self.google_credentials = self.config['PATHS'].get('google_credentials_json', '')
        self.openai_api_key = self.config['DEFAULT'].get('OpenAI_API_Key', '')

        # QMediaPlayer for audio playback
        self.audio_player = QMediaPlayer()

        # In-memory store for currently selected card
        self.current_card_data = None

        try:
            main_layout = QHBoxLayout()
            self.setLayout(main_layout)

            # ----------------- LEFT COLUMN: Deck combo + Filter + Card List -----------------
            left_layout = QVBoxLayout()

            # Deck + Filter row
            deck_filter_layout = QHBoxLayout()
            self.deck_combo = QComboBox()
            self.deck_combo.setMinimumWidth(200)
            self.deck_combo.currentIndexChanged.connect(self.on_deck_changed)
            deck_filter_layout.addWidget(QLabel("Select Imported Deck:"))
            deck_filter_layout.addWidget(self.deck_combo)

            self.filter_edit = QLineEdit()
            self.filter_edit.setPlaceholderText("Filter by native word...")
            self.filter_edit.textChanged.connect(self.on_filter_changed)
            deck_filter_layout.addWidget(self.filter_edit)

            refresh_btn = QPushButton("Refresh")
            refresh_btn.clicked.connect(self.load_anki_import_decks)
            deck_filter_layout.addWidget(refresh_btn)

            left_layout.addLayout(deck_filter_layout)

            # Card list
            self.card_list = QListWidget()
            self.card_list.itemClicked.connect(self.on_card_clicked)
            left_layout.addWidget(self.card_list, stretch=1)

            main_layout.addLayout(left_layout, stretch=1)

            # ----------------- RIGHT COLUMN: Card Detail Form -----------------
            self.detail_form = QGroupBox("Card Details")
            form_layout = QFormLayout(self.detail_form)

            # Card ID (read-only)
            self.field_card_id = QLineEdit()
            self.field_card_id.setReadOnly(True)
            form_layout.addRow("Card ID:", self.field_card_id)

            # Native Word
            self.field_native_word = QLineEdit()
            form_layout.addRow("Native Word:", self.field_native_word)

            # Translated Word
            self.field_translated_word = QLineEdit()
            form_layout.addRow("Translated Word:", self.field_translated_word)

            # POS
            self.field_pos = QLineEdit()
            form_layout.addRow("POS:", self.field_pos)

            # Reading
            self.field_reading = QLineEdit()
            form_layout.addRow("Reading:", self.field_reading)

            # Native Sentence
            self.field_native_sentence = QPlainTextEdit()
            self.field_native_sentence.setFixedHeight(60)
            form_layout.addRow("Native Sentence:", self.field_native_sentence)

            # Translated Sentence
            self.field_translated_sentence = QPlainTextEdit()
            self.field_translated_sentence.setFixedHeight(60)
            form_layout.addRow("Translated Sentence:", self.field_translated_sentence)

            # ----------------- AUDIO FIELDS -----------------
            # Word Audio
            audio_layout_word = QHBoxLayout()
            self.field_word_audio = QLineEdit()
            audio_layout_word.addWidget(self.field_word_audio)

            btn_play_word = QPushButton("Play")
            btn_play_word.clicked.connect(self.play_word_audio)
            audio_layout_word.addWidget(btn_play_word)

            btn_regen_word = QPushButton("Regen Audio")
            btn_regen_word.clicked.connect(self.regen_word_audio)
            audio_layout_word.addWidget(btn_regen_word)
            form_layout.addRow("Word Audio:", audio_layout_word)

            # Sentence Audio
            audio_layout_sentence = QHBoxLayout()
            self.field_sentence_audio = QLineEdit()
            audio_layout_sentence.addWidget(self.field_sentence_audio)

            btn_play_sentence = QPushButton("Play")
            btn_play_sentence.clicked.connect(self.play_sentence_audio)
            audio_layout_sentence.addWidget(btn_play_sentence)

            btn_regen_sentence = QPushButton("Regen Audio")
            btn_regen_sentence.clicked.connect(self.regen_sentence_audio)
            audio_layout_sentence.addWidget(btn_regen_sentence)
            form_layout.addRow("Sentence Audio:", audio_layout_sentence)

            # ----------------- IMAGE FIELD -----------------
            image_layout = QVBoxLayout()
            self.image_label = QLabel()
            self.image_label.setFixedSize(200, 200)
            self.image_label.setStyleSheet("border: 1px solid gray;")
            self.image_label.setScaledContents(True)
            image_layout.addWidget(self.image_label)

            btn_regen_image = QPushButton("Regen Image")
            btn_regen_image.clicked.connect(self.regen_image)
            image_layout.addWidget(btn_regen_image)

            form_layout.addRow("Sentence Image:", image_layout)

            # Spacer at bottom
            form_layout.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))

            # Add the group box to main layout
            main_layout.addWidget(self.detail_form, stretch=1)

            # Load decks
            self.load_anki_import_decks()

        except Exception as e:
            logger.exception("Exception in DeckEditorWindow.__init__: %s", e)
            traceback.print_exc()

    # -------------------------------------------------------------------------
    # Deck & Card Loading
    # -------------------------------------------------------------------------
    def load_anki_import_decks(self):
        logger.info("Entering load_anki_import_decks")
        try:
            self.deck_combo.clear()
            decks = self.db.get_anki_import_decks()
            logger.info(f"Found {len(decks)} anki_import decks: {decks}")

            if not decks:
                self.deck_combo.addItem("No Anki-Imported Decks Found")
                self.deck_combo.setEnabled(False)
                self.card_list.clear()
                self.clear_card_fields()
                return

            self.deck_combo.setEnabled(True)
            self.deck_combo.addItems(decks)
        except Exception as e:
            logger.exception("Error in load_anki_import_decks: %s", e)
            traceback.print_exc()

    def on_deck_changed(self):
        logger.info("Entering on_deck_changed")
        try:
            current_deck = self.deck_combo.currentText()
            logger.info(f"User selected deck: {current_deck}")
            self.load_cards_for_deck(current_deck)
        except Exception as e:
            logger.exception("Error in on_deck_changed: %s", e)
            traceback.print_exc()

    def load_cards_for_deck(self, deck_origin: str):
        logger.info(f"Entering load_cards_for_deck with deck_origin='{deck_origin}'")
        try:
            self.card_list.clear()
            self.clear_card_fields()
            if not deck_origin or "No Anki-Imported" in deck_origin:
                logger.info("Deck origin is invalid or no deck selected. Returning.")
                return

            self.all_cards = self.db.get_cards_by_deck_origin(deck_origin)
            logger.info(f"Retrieved {len(self.all_cards)} cards for deck_origin='{deck_origin}'")

            filter_text = self.filter_edit.text().strip().lower()
            logger.info(f"Current filter text: '{filter_text}'")

            for card in self.all_cards:
                native_word = card.get("native_word", "").lower()
                if filter_text in native_word:
                    item_text = f"[{card['card_id']}] {card['native_word']}"
                    list_item = QListWidgetItem(item_text)
                    list_item.setData(Qt.UserRole, card)
                    self.card_list.addItem(list_item)

        except Exception as e:
            logger.exception("Error in load_cards_for_deck: %s", e)
            traceback.print_exc()

    def on_filter_changed(self, text: str):
        logger.info(f"Entering on_filter_changed with text='{text}'")
        try:
            current_deck = self.deck_combo.currentText()
            if not current_deck or "No Anki-Imported" in current_deck:
                logger.info("Deck origin is invalid or no deck selected. Returning.")
                return

            self.card_list.clear()
            self.clear_card_fields()

            filter_text = text.strip().lower()
            for card in self.all_cards:
                native_word = card.get("native_word", "").lower()
                if filter_text in native_word:
                    item_text = f"[{card['card_id']}] {card['native_word']}"
                    list_item = QListWidgetItem(item_text)
                    list_item.setData(Qt.UserRole, card)
                    self.card_list.addItem(list_item)
        except Exception as e:
            logger.exception("Error in on_filter_changed: %s", e)
            traceback.print_exc()

    def on_card_clicked(self, item: QListWidgetItem):
        logger.info("Entering on_card_clicked")
        try:
            card_data = item.data(Qt.UserRole)
            if not card_data:
                logger.info("No card data found in item, returning.")
                return
            self.current_card_data = card_data
            self.populate_card_fields(card_data)

        except Exception as e:
            logger.exception("Error in on_card_clicked: %s", e)
            traceback.print_exc()

    # -------------------------------------------------------------------------
    # Card Field Helpers
    # -------------------------------------------------------------------------
    def clear_card_fields(self):
        """ Clear out the text boxes and image preview. """
        self.current_card_data = None
        self.field_card_id.setText("")
        self.field_native_word.setText("")
        self.field_translated_word.setText("")
        self.field_pos.setText("")
        self.field_reading.setText("")
        self.field_native_sentence.setPlainText("")
        self.field_translated_sentence.setPlainText("")
        self.field_word_audio.setText("")
        self.field_sentence_audio.setText("")
        self.image_label.clear()

    def populate_card_fields(self, card_data: dict):
        """
        Fill the UI fields with card_data. Also parse audio + image to
        display a real preview or make it playable.
        """
        logger.info(f"Populating fields for card: {card_data}")

        # Basic text fields
        self.field_card_id.setText(str(card_data.get("card_id", "")))
        self.field_native_word.setText(card_data.get("native_word", ""))
        self.field_translated_word.setText(card_data.get("translated_word", ""))
        self.field_pos.setText(card_data.get("pos", ""))
        self.field_reading.setText(card_data.get("reading", ""))
        self.field_native_sentence.setPlainText(card_data.get("native_sentence", ""))
        self.field_translated_sentence.setPlainText(card_data.get("translated_sentence", ""))

        # Word audio
        word_audio = card_data.get("word_audio", "")
        self.field_word_audio.setText(word_audio)

        # Sentence audio
        sentence_audio = card_data.get("sentence_audio", "")
        self.field_sentence_audio.setText(sentence_audio)

        # Load image
        self.load_image_from_html(card_data.get("image", ""))

    def load_image_from_html(self, image_html: str):
        """
        If we have an <img src="somefile.png">, try loading from self.anki_media_path + somefile.png
        """
        if not image_html.strip():
            self.image_label.setText("[No Image]")
            return

        match = re.search(r'<img\s+src="([^"]+)"', image_html)
        if not match:
            self.image_label.setText("[Invalid Image Tag]")
            return

        filename = match.group(1)
        image_path = os.path.join(self.anki_media_path, filename)
        if os.path.exists(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                pix = pix.scaled(self.image_label.width(), self.image_label.height(),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.image_label.setPixmap(pix)
            else:
                self.image_label.setText("[Invalid Image]")
        else:
            self.image_label.setText("[Image Not Found]")

    # -------------------------------------------------------------------------
    # AUDIO PLAYBACK
    # -------------------------------------------------------------------------
    def play_word_audio(self):
        """
        Extract [sound:filename] from self.field_word_audio if present,
        and play from anki_media_path.
        """
        word_audio_text = self.field_word_audio.text().strip()
        if not word_audio_text:
            logger.info("No word audio to play.")
            return

        match = re.search(r'\[sound:(.*?)\]', word_audio_text)
        if match:
            filename = match.group(1)
            audio_path = os.path.join(self.anki_media_path, filename)
            if not os.path.exists(audio_path):
                logger.info(f"Audio file not found: {audio_path}")
                return
            logger.info(f"Playing word audio from {audio_path}")
            self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(audio_path)))
            self.audio_player.play()
        else:
            logger.info("No valid [sound:filename] pattern found for word audio.")

    def play_sentence_audio(self):
        """
        Extract [sound:filename] from self.field_sentence_audio if present,
        and play from anki_media_path.
        """
        sentence_audio_text = self.field_sentence_audio.text().strip()
        if not sentence_audio_text:
            logger.info("No sentence audio to play.")
            return

        match = re.search(r'\[sound:(.*?)\]', sentence_audio_text)
        if match:
            filename = match.group(1)
            audio_path = os.path.join(self.anki_media_path, filename)
            if not os.path.exists(audio_path):
                logger.info(f"Audio file not found: {audio_path}")
                return
            logger.info(f"Playing sentence audio from {audio_path}")
            self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(audio_path)))
            self.audio_player.play()
        else:
            logger.info("No valid [sound:filename] pattern found for sentence audio.")

    # -------------------------------------------------------------------------
    # AI REGEN IMPLEMENTATIONS (with DB + Anki updates)
    # -------------------------------------------------------------------------
    def regen_word_audio(self):
        """
        Re-generate the word audio using AI TTS, store in Anki, update local DB + Anki note field.
        """
        if not self.current_card_data:
            return
        card_id = self.current_card_data.get("card_id")
        native_word = self.field_native_word.text().strip()
        if not native_word:
            logger.info("No native word found; cannot generate audio.")
            return

        logger.info("Regenerating word audio via Google TTS...")

        # Setup credentials
        if not os.path.exists(self.google_credentials):
            logger.info("No or invalid Google credentials JSON; cannot generate TTS.")
            return
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.google_credentials
        client = texttospeech.TextToSpeechClient()

        # Generate TTS
        try:
            synthesis_input = texttospeech.SynthesisInput(text=native_word)
            voice = texttospeech.VoiceSelectionParams(
                language_code="ja-JP",
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            # Store in Anki
            audio_filename = f"word_audio_{uuid.uuid4().hex}.mp3"
            b64_data = base64.b64encode(response.audio_content).decode('utf-8')
            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                logger.info(f"Failed to store audio {audio_filename} in Anki.")
                return

            # Build new [sound:filename]
            new_audio_tag = f"[sound:{audio_filename}]"

            # 1) Update local DB
            self.db.update_card_audio(card_id, "word", new_audio_tag)

            # 2) Update in-memory
            self.field_word_audio.setText(new_audio_tag)
            self.current_card_data["word_audio"] = new_audio_tag

            # 3) Update Anki note field (assuming your Anki note field is "Word Audio" or similar)
            anki_card_id = self.db.get_anki_card_id(card_id)
            logger.info(f"Got Anki card ID: {anki_card_id}")
            if anki_card_id:
                # Suppose your model’s audio field is named "Word Audio". Adjust as needed.
                logger.info(f"Updating Anki note field for card ID {anki_card_id}")
                self.db.update_anki_note_field(anki_card_id, "word audio", new_audio_tag)

            logger.info(f"Regen word audio success => {new_audio_tag}")

        except Exception as e:
            logger.exception(f"Exception while regenerating word audio: {e}")

    def regen_sentence_audio(self):
        """
        Re-generate sentence audio for self.field_native_sentence, store in Anki, update local DB + Anki note field.
        """
        if not self.current_card_data:
            return
        card_id = self.current_card_data.get("card_id")
        native_sentence = self.field_native_sentence.toPlainText().strip()
        if not native_sentence:
            logger.info("No native sentence found; cannot generate audio.")
            return

        logger.info("Regenerating sentence audio via Google TTS...")

        if not os.path.exists(self.google_credentials):
            logger.info("No or invalid Google credentials JSON; cannot generate TTS.")
            return
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.google_credentials
        client = texttospeech.TextToSpeechClient()

        # Generate TTS
        try:
            synthesis_input = texttospeech.SynthesisInput(text=native_sentence)
            voice = texttospeech.VoiceSelectionParams(
                language_code="ja-JP",
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            # Store in Anki
            audio_filename = f"sentence_audio_{uuid.uuid4().hex}.mp3"
            b64_data = base64.b64encode(response.audio_content).decode('utf-8')
            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                logger.info(f"Failed to store audio {audio_filename} in Anki.")
                return

            new_audio_tag = f"[sound:{audio_filename}]"

            # 1) Update local DB
            self.db.update_card_audio(card_id, "sentence", new_audio_tag)

            # 2) Update in-memory
            self.field_sentence_audio.setText(new_audio_tag)
            self.current_card_data["sentence_audio"] = new_audio_tag

            # 3) Update Anki note field (assuming your Anki note field is "Sentence Audio")
            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "sentence audio", new_audio_tag)

            logger.info(f"Regen sentence audio success => {new_audio_tag}")

        except Exception as e:
            logger.exception(f"Exception while regenerating sentence audio: {e}")

    def regen_image(self):
        """
        Re-generate the image using DALL·E, store in Anki, update local DB + Anki note field.
        """
        if not self.current_card_data:
            return
        card_id = self.current_card_data.get("card_id")
        native_sentence = self.field_native_sentence.toPlainText().strip()
        if not native_sentence:
            logger.info("No native sentence found; cannot generate image.")
            return

        logger.info("Regenerating image via OpenAI DALL·E...")

        if not self.openai_api_key:
            logger.info("No OpenAI API key in config; cannot generate image.")
            return
        openai.api_key = self.openai_api_key

        try:
            prompt = f"Create a detailed and accurate illustration for this sentence: '{native_sentence}'"
            response = openai.Image.create(
                prompt=prompt,
                n=1,
                size="1024x1024",
                model="dall-e-3"
            )
            image_url = response['data'][0]['url']
            image_data = requests.get(image_url).content

            image_filename = f"sentence_image_{uuid.uuid4().hex}.png"
            b64_data = base64.b64encode(image_data).decode('utf-8')

            res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
            if res is None:
                logger.info(f"Failed to store image {image_filename} in Anki.")
                return

            # Build new <img src="filename">
            new_img_html = f'<img src="{image_filename}">'

            # 1) Update local DB
            self.db.update_card_image(card_id, new_img_html)

            # 2) Update in-memory
            self.current_card_data["image"] = new_img_html
            self.load_image_from_html(new_img_html)

            # 3) Update Anki note field (assuming the Anki field is "Image" or similar)
            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "image", new_img_html)

            logger.info(f"Regen image success => {new_img_html}")

        except Exception as e:
            logger.exception(f"Exception while regenerating image: {e}")


