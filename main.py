import base64
import json
import sys
import os
import logging
import uuid
from os.path import basename
from pathlib import Path
from typing import Optional

import openai
import requests
import re
from file_utils import normalize_filename, parse_filename_for_show_episode
import metadata_utils


# -------------------------------------------------------------------
# 1) Prepend DLL directory to PATH before importing mpv (Windows).
#    If you're bundling with PyInstaller, place libmpv-2.dll alongside
#    the executable or in sys._MEIPASS, then set script_directory accordingly.
# -------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    script_directory = sys._MEIPASS
else:
    script_directory = os.path.dirname(os.path.abspath(__file__))

# Append to PATH so mpv can find libmpv-2.dll
os.environ["PATH"] = script_directory + os.pathsep + os.environ["PATH"]

try:
    import mpv
except ImportError as e:
    print("Failed to import mpv:", e)
    sys.exit(1)

from PyQt5.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QWidget,
    QToolBar,
    QAction,
    QActionGroup,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QPushButton,
    QTextEdit,
    QFileDialog,
    QSpacerItem,
    QSizePolicy,
    QListWidgetItem,
    QLineEdit,
    QPlainTextEdit,
    QFormLayout,
    QGroupBox,
    QListWidget,
    QComboBox,
    QScrollArea,
    QCheckBox, QMessageBox, QDialog, QTabWidget, QSlider, QMenu, QSpinBox,
    QDialogButtonBox
)
from google.cloud import texttospeech

from content_parser import ContentParser
from deck_field_mapping_dialog import DeckFieldMappingDialog
from metadata_edit_dialog import MetadataEditDialog
from subtitle_window import SubtitleWindow
from subtitles import SubtitleManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CentralHub")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi"}  # extend as you like
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass"}


### NEW CODE: build_directory_tree
def build_directory_tree(media_rows):
    """
    Given a list of (media_id, file_path) rows,
    returns a nested dictionary representing the folder hierarchy.

    Example:
        {
          "C:": {
            "Videos": {
              "Anime": {
                "__files__": [
                  ("C:/Videos/Anime/Episode1.mkv", 101),
                  ("C:/Videos/Anime/Episode2.mkv", 102)
                ]
              }
            }
          }
        }
    """
    import os
    tree = {}

    for media_id, file_path in media_rows:
        norm_path = os.path.normpath(file_path)  # normalize path separators
        folder_part, filename = os.path.split(norm_path)
        parts = folder_part.split(os.sep)

        # Walk the nested dict structure
        current_level = tree
        for p in parts:
            if p not in current_level:
                current_level[p] = {}
            current_level = current_level[p]

        # At the final folder level, add the file to a __files__ list
        if "__files__" not in current_level:
            current_level["__files__"] = []
        current_level["__files__"].append((os.path.join(folder_part, filename), media_id))

    return tree

import configparser
import os

def ensure_config():
    """
    Ensures we have a 'config.ini' file.
    If not found, creates a minimal one with an empty [FIELD_MAPPINGS] section.
    """
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.ini')

    if not os.path.exists(CONFIG_PATH):
        print(f"No config.ini found. Creating a minimal one at {CONFIG_PATH}")
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            # Provide a DEFAULT section with placeholder API keys so users
            # know what can be configured.
            f.write("[DEFAULT]\n")
            f.write("OpenAI_API_Key =\n")
            f.write("TMDB_API_Key =\n\n")

            # Section used by the deck field mapping dialog
            f.write("[FIELD_MAPPINGS]\n")
    # Otherwise, it already exists

    # Now read it
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    return config, CONFIG_PATH

def build_relative_directory_tree(media_rows, base_folder):
    """
    media_rows: list of (media_id, file_path)
    base_folder: the source folder path to subtract

    Returns a nested dict for subfolders/files under `base_folder`.
    Example structure:
    {
      "Mushoku Tensei": {
         "__files__": [
             ("C:/.../Test/Mushoku Tensei/Mushoku Tensei 01.mkv", 123)
         ],
         ...
      }
    }
    """
    import os
    tree = {}
    base_folder = os.path.normpath(base_folder)

    for (media_id, file_path) in media_rows:
        norm_path = os.path.normpath(file_path)
        rel_path = os.path.relpath(norm_path, base_folder)
        if rel_path.startswith(".."):
            # skip files that are not physically under base_folder
            continue

        folder_part, filename = os.path.split(rel_path)
        parts = folder_part.split(os.sep) if folder_part != "." else []

        current_level = tree
        for p in parts:
            if p not in current_level:
                current_level[p] = {}
            current_level = current_level[p]

        if "__files__" not in current_level:
            current_level["__files__"] = []
        current_level["__files__"].append((norm_path, media_id))

    return tree

def format_time(seconds: float) -> str:
    """
    Convert float seconds into hh:mm:ss string.
    """
    if seconds < 0:
        seconds = 0
    secs = int(seconds)
    hours = secs // 3600
    mins = (secs % 3600) // 60
    secs = secs % 60
    return f"{hours:02}:{mins:02}:{secs:02}"

class ClickableSlider(QSlider):
    """
    A QSlider that lets you click anywhere on the track to jump immediately.
    """
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Calculate the proportion along the slider based on click position
            x = event.pos().x()
            total_w = self.width()
            new_val = self.minimum() + (self.maximum() - self.minimum()) * (x / float(total_w))
            self.setValue(int(new_val))
        super().mousePressEvent(event)


# -------------------------------------------------------------------
# 2) A custom mpv-based video widget with Play/Pause and a scrub slider
# -------------------------------------------------------------------
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QLabel, QMessageBox
)
import mpv
import os


class MyVideoPlayerWidget(QWidget):
    playbackTimeChanged = pyqtSignal(float)
    openSubtitleWindowRequested = pyqtSignal()
    def __init__(self, mpv_uri: str,db_manager, media_id: Optional[int] = None, parent=None):
        super().__init__(parent)

        self.setContentsMargins(0, 0, 0, 0)
        logger.info(f"Creating video player for: {mpv_uri}")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.video_container = QFrame()
        main_layout.addWidget(self.video_container, stretch=1)
        self.video_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_container.mouseDoubleClickEvent = self.on_video_double_click

        # We do NOT do "file://" + ... again.
        # Just store the already-correct mpv_uri from the DB:
        self.mpv_uri = mpv_uri
        self.media_id = media_id
        self.db = db_manager


        # If you want to check existence locally, you can do that with
        # the raw "file_path" *before* you come here.
        # Inside here, 'os.path.exists(self.mpv_uri)' won't work
        # because mpv_uri is not a plain path.

        self.player = mpv.MPV(
            wid=int(self.video_container.winId()),
            input_default_bindings=True,
            input_vo_keyboard=True,
            pause=False
        )
        self.player["hr-seek"] = "yes"
        self.player["volume"] = 200
        self.player["sid"] = "no"  # no subtitles by default
        logger.info(f"Playing video: {self.mpv_uri}")
        self.player.play(self.mpv_uri)
        logger.info("Video playback started.")

        # ------------------------
        # 2) Bottom Controls
        # ------------------------
        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(5, 5, 5, 5)
        controls_layout.setSpacing(10)

        # a) Play/Pause
        self.btn_playpause = QPushButton("Pause")
        self.btn_playpause.clicked.connect(self.toggle_play_pause)
        controls_layout.addWidget(self.btn_playpause)

        # b) Slider
        self.slider = ClickableSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        controls_layout.addWidget(self.slider, stretch=1)

        # c) Time label (e.g. "00:00:00 / 00:00:00")
        self.time_label = QLabel("00:00:00 / 00:00:00")
        controls_layout.addWidget(self.time_label)

        main_layout.addWidget(controls_frame, stretch=0)

        # QTimer to update slider/time label
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(500)  # ms
        self.update_timer.timeout.connect(self.update_slider)
        self.update_timer.start()

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self.is_dragging_slider = False
        logger.info("Video player widget initialized.")

    def on_video_double_click(self, event):
        # When user double-clicks the video, request fullscreen toggle
        main_window = self.window()  # get the top-level window
        if main_window:
            main_window.toggle_fullscreen()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        action_play_pause = menu.addAction("Play/Pause")
        action_next_sub = menu.addAction("Next Subtitle")
        action_prev_sub = menu.addAction("Previous Subtitle")
        action_open_sub_window = menu.addAction("Open Subtitle Window")

        # New audio cycling action:
        action_cycle_audio = menu.addAction("Cycle Audio Track")

        selected_action = menu.exec_(event.globalPos())

        if selected_action == action_play_pause:
            self.toggle_play_pause()
        elif selected_action == action_next_sub:
            self.jump_to_next_subtitle()
        elif selected_action == action_prev_sub:
            self.jump_to_previous_subtitle()
        elif selected_action == action_open_sub_window:
            self.openSubtitleWindowRequested.emit()
        elif selected_action == action_cycle_audio:
            # Cycle audio track in mpv
            self.player.command("cycle", "aid")

        event.accept()

    def request_subtitle_window(self):
        # Access our parent (the MainWindow or CentralHub)
        parent = self.parent()
        if parent and hasattr(parent, "open_subtitle_window"):
            parent.open_subtitle_window()
        else:
            print("No parent or no open_subtitle_window method available.")

    def jump_to_next_subtitle(self):
        logger.info("Jumping to next subtitle.")
        if not self.media_id:
            logger.info("No media_id found.")
            return
        logger.info(f"Media ID: {self.media_id}")
        current_time = self.player.time_pos or 0.0
        logger.info(f"Current time: {current_time}")
        result = self.db.get_next_subtitle(self.media_id, current_time)
        logger.info(f"Next subtitle result: {result}")
        if result:
            (start_time, end_time, text) = result
            self.player.seek(start_time, reference="absolute", precision="exact")
            self.player.pause = False  # If you want to auto‐play
        else:
            print("No next subtitle found.")

    def jump_to_previous_subtitle(self):
        if not self.media_id:
            return

        current_time = self.player.time_pos or 0.0

        # 1) Check if we are inside a line
        inside_line = self.db.get_subtitle_for_time(self.media_id, current_time)
        if inside_line:
            (start_s, end_s, text) = inside_line
            # If we want to skip the line we're currently in, we pick a new
            # "search time" that is slightly before this line's start.
            offset_time = max(start_s - 0.1, 0)
            # Then re‐run get_previous_subtitle using that offset_time
            line = self.db.get_previous_subtitle(self.media_id, offset_time)
        else:
            # 2) If we are NOT inside any line, just do a normal “previous” from current_time
            line = self.db.get_previous_subtitle(self.media_id, current_time)

        if line:
            (start_time, end_time, content) = line
            self.player.seek(start_time, reference="absolute", precision="exact")
            self.player.pause = False
        else:
            print("No previous subtitle found.")

    # -------------------------
    # Helpers
    # -------------------------
    def toggle_play_pause(self):
        """
        Flip mpv's pause state. If it's paused, unpause; if playing, pause.
        """
        self.player.pause = not self.player.pause
        if self.player.pause:
            self.btn_playpause.setText("Play")
        else:
            self.btn_playpause.setText("Pause")

    def on_slider_pressed(self):
        self.is_dragging_slider = True

    def on_slider_released(self):
        self.is_dragging_slider = False
        val = self.slider.value()
        duration = self.player.duration or 1
        new_pos = (val / 1000.0) * duration
        self.player.seek(new_pos, reference="absolute", precision="exact")

    def update_slider(self):
        """
        Periodically called by QTimer to reflect the current
        mpv playback position & total duration in the slider/time_label.
        """
        if self.is_dragging_slider:
            return  # don't move the slider if user is dragging

        pos = self.player.time_pos or 0.0
        dur = self.player.duration or 0.0

        if dur > 0:
            fraction = pos / dur
        else:
            fraction = 0.0

        self.slider.setValue(int(fraction * 1000))

        # Update time label
        current_str = format_time(pos)
        duration_str = format_time(dur)
        self.time_label.setText(f"{current_str} / {duration_str}")
        self.playbackTimeChanged.emit(pos)

    def get_system_path(self):
        """Return the original system path from DB."""
        return self.raw_system_path


class CentralHub(QMainWindow):
    def __init__(self, db_manager, anki_connector=None):
        super().__init__()
        self.db = db_manager
        self.subtitle_window = None  # if you want a shared instance
        self._subtitle_lines = []  # (sentence_id, text) pairs for current video
        self.anki = anki_connector
        self.parser = ContentParser()

        config, config_path = ensure_config()
        self.config = config
        self.config_path = config_path

        self.setWindowTitle("CRS Central Hub - Complete Example")
        self.setMinimumSize(1000, 600)

        # Inside CentralHub.__init__:

        # Already have self.config from ensure_config() ...
        self.anki_media_path = self.config.get("PATHS", "anki_media_path", fallback="")
        self.google_credentials = self.config.get("PATHS", "google_credentials_json", fallback="")
        self.openai_api_key = self.config.get("DEFAULT", "OpenAI_API_Key", fallback="")
        self.tmdb_api_key = self.config.get("DEFAULT", "TMDB_API_Key", fallback="")

        metadata_utils.TMDB_API_KEY = self.tmdb_api_key
        metadata_utils.DB_MANAGER = self.db

        # Create a QMediaPlayer for playing audio in the Deck Editor
        self.audio_player = QMediaPlayer()

        # Variables to track the current "explore" sentence
        self.explore_sentence_id = None
        self.explore_sentence_text = None
        self.explore_current_audio_file = None
        self.explore_checkboxes = {}  # dict_form_id -> QCheckBox

        ######################################################################
        # 1) Main Stacked Widget (Two Tabs: Media Browser & Anki Manager)
        ######################################################################
        self.main_stack = QStackedWidget()
        self.setCentralWidget(self.main_stack)

        # Create the two pages
        self.page_media_browser = self.create_media_browser_page()
        self.page_anki_manager = self.create_anki_manager_page()

        # Add them to the stacked widget
        self.main_stack.addWidget(self.page_media_browser)  # index 0
        self.main_stack.addWidget(self.page_anki_manager)   # index 1

        # Default page: Media Browser
        self.main_stack.setCurrentIndex(0)

        # 1) Create the Video Player page
        self.page_video_tabs = self.create_video_tabs_page()
        self.main_stack.addWidget(self.page_video_tabs)  # index 2

        ######################################################################
        # 2) TOP-LEVEL TOOLBAR (Tabs / Navigation Between Pages)
        ######################################################################
        self.top_toolbar = QToolBar("Top Toolbar")
        self.top_toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.top_toolbar)

        # Create checkable actions for "tabs"
        self.action_show_browser = QAction("Media Browser", self)
        self.action_show_browser.setCheckable(True)
        self.action_show_anki_manager = QAction("Anki Manager", self)
        self.action_show_anki_manager.setCheckable(True)

        # Put these actions in an exclusive group
        self.tab_action_group = QActionGroup(self)
        self.tab_action_group.setExclusive(True)
        self.tab_action_group.addAction(self.action_show_browser)
        self.tab_action_group.addAction(self.action_show_anki_manager)

        # Add actions to the top toolbar
        self.top_toolbar.addAction(self.action_show_browser)
        self.top_toolbar.addAction(self.action_show_anki_manager)

        # Connect them to the page-switching method
        self.action_show_browser.triggered.connect(lambda: self.set_main_page(0))
        self.action_show_anki_manager.triggered.connect(lambda: self.set_main_page(1))

        # Default checked action
        self.action_show_browser.setChecked(True)

        ######################################################################
        # 3) FORCE A NEW ROW FOR SUB-TOOLBARS
        ######################################################################
        self.addToolBarBreak(Qt.TopToolBarArea)

        ######################################################################
        # 4) SUB-TOOLBARS (One for each page)
        ######################################################################
        # Media Browser Toolbar
        self.media_browser_toolbar = QToolBar("Media Browser Toolbar")
        self.media_browser_toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.media_browser_toolbar)

        self.action_add_source = QAction("Add Source Folder", self)
        self.action_add_source.triggered.connect(self.add_source_folder)
        self.media_browser_toolbar.addAction(self.action_add_source)

        self.action_rescan = QAction("Re-Scan All Sources", self)
        self.action_rescan.triggered.connect(self.rescan_all_sources)
        self.media_browser_toolbar.addAction(self.action_rescan)

        self.action_remove_source = QAction("Remove Source", self)
        self.action_remove_source.triggered.connect(self.remove_source)
        self.media_browser_toolbar.addAction(self.action_remove_source)

        # Anki Manager Toolbar
        self.anki_manager_toolbar = QToolBar("Anki Manager Toolbar")
        self.anki_manager_toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.anki_manager_toolbar)

        self.action_sync_anki = QAction("Sync Anki", self)
        self.action_sync_anki.triggered.connect(self.sync_anki)
        self.anki_manager_toolbar.addAction(self.action_sync_anki)

        self.action_update_coverage = QAction("Update Coverage", self)
        self.action_update_coverage.triggered.connect(self.update_coverage)
        self.anki_manager_toolbar.addAction(self.action_update_coverage)

        self.action_parse_kanji = QAction("Parse Kanji", self)
        self.action_parse_kanji.triggered.connect(self.parse_pending_kanji)
        self.anki_manager_toolbar.addAction(self.action_parse_kanji)

        # Initially show the Media Browser Toolbar, hide the Anki Manager Toolbar
        self.media_browser_toolbar.setVisible(True)
        self.anki_manager_toolbar.setVisible(False)

        # Track page changes to show/hide correct sub-toolbar
        self.main_stack.currentChanged.connect(self.on_main_stack_changed)

        # -- Create the Study page and add to the main stack
        self.page_study = self.create_study_page()
        self.main_stack.addWidget(self.page_study)  # This will be index 3

        # -- Create an action for “Study”
        self.action_show_study = QAction("Study", self)
        self.action_show_study.setCheckable(True)
        self.tab_action_group.addAction(self.action_show_study)
        self.top_toolbar.addAction(self.action_show_study)

        self.study_toolbar = QToolBar("Study Toolbar")
        self.study_toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.study_toolbar)

        #############################################################
        # Near where you define and group other top-level "tab" actions
        #############################################################

        self.action_show_video = QAction("Video", self)
        self.action_show_video.setCheckable(True)
        self.tab_action_group.addAction(self.action_show_video)
        self.top_toolbar.addAction(self.action_show_video)

        # Connect it to switch the main stack to index 2 (your video page index)
        self.action_show_video.triggered.connect(lambda: self.set_main_page(2))

        # Create actions for the 3 subtabs:
        self.action_study_explore = QAction("Explore New Words", self)
        self.action_study_set = QAction("Set Target Material", self)

        self.populate_study_filter_combo()
        self.load_study_materials()

        # NEW:
        self.action_study_cards = QAction("Cards", self)
        self.action_study_kanji = QAction("Kanji", self)

        # Add them all to the study_toolbar:
        self.study_toolbar.addAction(self.action_study_explore)
        self.study_toolbar.addAction(self.action_study_set)
        self.study_toolbar.addAction(self.action_study_cards)
        self.study_toolbar.addAction(self.action_study_kanji)

        # Connect each to a function that switches sub-pages
        self.action_study_explore.triggered.connect(
            lambda: self.study_stack.setCurrentWidget(self.page_study_explore)
        )
        self.action_study_set.triggered.connect(
            lambda: self.study_stack.setCurrentWidget(self.page_study_set)
        )
        self.action_study_cards.triggered.connect(
            lambda: self.study_stack.setCurrentWidget(self.page_study_cards)
        )
        self.action_study_kanji.triggered.connect(
            lambda: self.study_stack.setCurrentWidget(self.page_study_kanji)
        )

        self.study_filter_combo.currentIndexChanged.connect(self.load_study_materials)

        # Possibly group them if you want them checkable/exclusive:
        # study_action_group = QActionGroup(self)
        # study_action_group.setExclusive(True)
        # ...
        # Or just add them directly:
        self.study_toolbar.addAction(self.action_study_explore)
        self.study_toolbar.addAction(self.action_study_set)

        # Connect each to a function that switches sub-pages
        self.action_study_explore.triggered.connect(
            lambda: self.study_stack.setCurrentWidget(self.page_study_explore)
        )
        self.action_study_set.triggered.connect(
            lambda: self.study_stack.setCurrentWidget(self.page_study_set)
        )

        # Initially hidden, will show only when the Study page is active
        self.study_toolbar.setVisible(False)

        # Connect to switch the main stack to Study when triggered
        self.action_show_study.triggered.connect(lambda: self.set_main_page(3))
        self.study_stack.currentChanged.connect(self.on_study_stack_changed)
        ######################################################################
        # Status Bar
        ######################################################################
        # self.load_directory_tree_for_source()
        self.statusBar().showMessage("Ready")

        fullscreen_action = QAction("Toggle Full Screen", self)
        fullscreen_action.setShortcut(Qt.Key_F)  # or QKeySequence("F")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(fullscreen_action)  # make sure the action is enabled for key shortcuts

    ##########################################################################
    # Switching Between the Two Main Pages (and Video, Study)
    ##########################################################################
    def set_main_page(self, index: int):
        self.main_stack.setCurrentIndex(index)
        if index == 0:
            self.action_show_browser.setChecked(True)
        elif index == 1:
            self.action_show_anki_manager.setChecked(True)
        elif index == 2:
            # Video Tabs Page
            self.media_browser_toolbar.setVisible(False)
            self.anki_manager_toolbar.setVisible(False)
            self.study_toolbar.setVisible(False)
            self.action_show_video.setChecked(True)
            if hasattr(self, "video_toolbar"):
                self.video_toolbar.setVisible(True)
            pass
        elif index == 3:
            self.action_show_study.setChecked(True)

    def toggle_fullscreen(self):
        if not self.isFullScreen():
            self.showFullScreen()  # enter full screen mode:contentReference[oaicite:0]{index=0}
        else:
            self.showNormal()  # exit full screen mode:contentReference[oaicite:1]{index=1}

    def on_study_stack_changed(self, new_index: int):
        # Check if the new page is your Explore page
        new_widget = self.study_stack.widget(new_index)
        if new_widget == self.page_study_explore:
            # Now load the random sentence only when user lands on Explore
            self.load_random_sentence_explore()
        elif new_widget == self.page_study_kanji:
            self.refresh_deferred_kanji_count()

    def jump_to_time(self, start_time: float):
        """
        Called when SubtitleWindow emits the subtitleDoubleClicked signal.
        We need to find the currently active video tab and tell it to seek.
        """
        logger.info(f"MainWindow: Jumping to time {start_time} seconds.")

        # Find the currently selected tab in self.video_tab_widget
        current_index = self.video_tab_widget.currentIndex()
        if current_index < 0:
            # No video tab is open
            logger.info("No video tabs are open, so cannot jump to time.")
            return

        player_widget = self.video_tab_widget.widget(current_index)
        if not player_widget or not hasattr(player_widget, "player"):
            logger.info("The current tab does not have a valid mpv player.")
            return

        # Now call mpv’s seek. If your code uses an absolute reference:
        player_widget.player.seek(start_time, reference="absolute", precision="exact")
        # or player_widget.player.command("seek", start_time, "absolute")

        # Optionally, if you wanted to unpause automatically:
        player_widget.player.pause = False

        logger.info(f"Sought active video tab to {start_time} seconds.")

    def remove_source(self):
        """Remove the selected source, show, or episode and all its associated data."""
        try:
            item = self.tree_widget.currentItem()
            if not item:
                self.statusBar().showMessage("Please select an item to remove.")
                return

            user_data = item.data(0, Qt.UserRole)

            # Determine actual path from user_data
            if isinstance(user_data, tuple):
                if len(user_data) >= 3 and isinstance(user_data[2], str):
                    item_path = user_data[2]  # e.g., ("media_file", id, path)
                elif len(user_data) >= 2 and isinstance(user_data[1], str):
                    item_path = user_data[1]  # e.g., ("folder", path)
                else:
                    raise TypeError(f"Tuple in UserRole lacks valid path: {user_data}")
            elif isinstance(user_data, str):
                item_path = user_data
            else:
                raise TypeError(f"Unsupported UserRole data: {user_data}")

            reply = QMessageBox.question(
                self, "Remove",
                f"Remove selected item and all related data?\n\n{item_path}",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply != QMessageBox.Yes:
                self.statusBar().showMessage("Remove canceled.")
                return

            success = self.db.remove_path(item_path)

            if success:
                self.load_all_sources_as_relative_trees()
                self.statusBar().showMessage(f"Item removed: {item_path}")
            else:
                self.statusBar().showMessage("Failed to remove item.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(e)}")

    def on_main_stack_changed(self, index):
        """
        Called whenever the stacked widget changes pages.
        We must show/hide the correct toolbars based on index.
        """
        if index == 0:
            # Media Browser
            self.media_browser_toolbar.setVisible(True)
            self.anki_manager_toolbar.setVisible(False)
            self.study_toolbar.setVisible(False)
        elif index == 1:
            # Anki Manager
            self.media_browser_toolbar.setVisible(False)
            self.anki_manager_toolbar.setVisible(True)
            self.study_toolbar.setVisible(False)
        elif index == 2:
            # Video Player
            self.media_browser_toolbar.setVisible(False)
            self.anki_manager_toolbar.setVisible(False)
            self.study_toolbar.setVisible(False)
        elif index == 3:
            # Study
            self.media_browser_toolbar.setVisible(False)
            self.anki_manager_toolbar.setVisible(False)
            self.study_toolbar.setVisible(True)

    ##########################################################################
    # Page 1: Media Browser
    ##########################################################################
    def cleanup_missing_files(self):
        """
        Removes 'media' rows and 'subtitles' rows for files that no longer exist on disk.
        """
        self.statusBar().showMessage("Cleaning up missing media entries...")
        cur = self.db._conn.cursor()

        # 1) Remove missing media
        cur.execute("SELECT media_id, file_path FROM media")
        all_media = cur.fetchall()
        for media_id, file_path in all_media:
            if not os.path.exists(file_path):
                self.statusBar().showMessage(f"Removing missing media: {file_path}")
                cur.execute("DELETE FROM media WHERE media_id = ?", (media_id,))
                # Also remove associated subtitles
                cur.execute("DELETE FROM subtitles WHERE media_id = ?", (media_id,))

        self.db._conn.commit()

        # 2) Remove missing subtitles
        cur.execute("SELECT sub_id, subtitle_file FROM subtitles")
        all_subs = cur.fetchall()
        for sub_id, sub_file in all_subs:
            if not os.path.exists(sub_file):
                self.statusBar().showMessage(f"Removing missing subtitle: {sub_file}")
                cur.execute("DELETE FROM subtitles WHERE sub_id = ?", (sub_id,))

        self.db._conn.commit()

    def normalize_filename(self, stem: str) -> str:
        """Wrapper around :func:`file_utils.normalize_filename`."""
        return normalize_filename(stem)

    def walk_and_index(self, folder_path: str):
        logger.info(f"Starting walk_and_index for folder: {folder_path}")

        folder = Path(folder_path)
        all_files = list(folder.rglob("*"))
        logger.info(f"Found {len(all_files)} total files/folders in '{folder_path}'")

        videos = []
        subtitles = []
        for fpath in all_files:
            if not fpath.is_file():
                continue
            ext = fpath.suffix.lower()
            if ext in VIDEO_EXTENSIONS:
                videos.append(fpath)
            elif ext in SUBTITLE_EXTENSIONS:
                subtitles.append(fpath)

        logger.info(f"Number of video files found: {len(videos)}")
        logger.info(f"Number of subtitle files found: {len(subtitles)}")

        # ------------------------------------------------------------
        # Prepare two maps:
        #   1) exact map:     { exact_stem: (media_id, vid_path) }
        #   2) normalized map { normalized_stem: (media_id, vid_path) }
        # ------------------------------------------------------------
        video_map_exact = {}
        video_map_normalized = {}

        for vid_path in videos:
            try:
                media_id = self.db.add_media(str(vid_path), media_type="video")
                exact_stem = vid_path.stem
                norm_stem = self.normalize_filename(exact_stem)
                show, season, episode = parse_filename_for_show_episode(exact_stem)
                logger.info(
                    f"Video path='{vid_path}', exact_stem='{exact_stem}', norm_stem='{norm_stem}' => media_id={media_id}")
                logger.debug(
                    f"Parsed title='{show}', season={season}, episode={episode}")

                video_map_exact[exact_stem] = (media_id, vid_path)
                video_map_normalized[norm_stem] = (media_id, vid_path)

                if not self.db.media_has_description(media_id):
                    try:
                        metadata_utils.fetch_and_store_metadata(media_id, show, season, episode)
                    except Exception as fetch_err:
                        logger.exception(f"Metadata fetch failed for {vid_path}: {fetch_err}")
            except Exception as e:
                logger.exception(f"Error adding media {vid_path}: {e}")

        for sub_path in subtitles:
            try:
                sub_stem = sub_path.stem
                logger.info(f"Processing subtitle='{sub_path}', exact_stem='{sub_stem}'")

                exact_match = video_map_exact.get(sub_stem)
                if exact_match:
                    # We found an exact match
                    (media_id, matching_vid) = exact_match
                    logger.info(
                        f"Exact match found for subtitle '{sub_path}' => media_id={media_id} (video='{matching_vid}')")
                else:
                    # Attempt normalized match
                    norm_sub_stem = self.normalize_filename(sub_stem)
                    fallback_match = video_map_normalized.get(norm_sub_stem)
                    if fallback_match:
                        (media_id, matching_vid) = fallback_match
                        logger.info(
                            f"Normalized match found for subtitle '{sub_path}' => media_id={media_id} (video='{matching_vid}')")
                    else:
                        logger.warning(
                            f"No matching video found for subtitle '{sub_path}' (stem='{sub_stem}', normalized='{norm_sub_stem}')")
                        continue

                # At this point, we have media_id for a matching video
                if self.db.subtitle_already_exists(str(sub_path)):
                    logger.info(f"Subtitle '{sub_path}' already in DB; skipping.")
                    continue

                # Add subtitle
                logger.info(f"Adding subtitle '{sub_path}' for media_id={media_id}")
                self.db.add_subtitle(
                    media_id=media_id,
                    subtitle_file=str(sub_path),
                    language="unknown",
                    format=sub_path.suffix.lstrip(".")
                )
                self.index_subtitle_file(media_id, str(sub_path))

            except Exception as e:
                logger.exception(f"Error processing subtitle '{sub_path}': {e}")

        logger.info(f"Done scanning folder: {folder_path}")

    def index_subtitle_file(self, media_id, subtitle_path):
        """
        Parse each line from 'subtitle_path' using SubtitleManager,
        store them in 'sentences' via self.db.add_text_source, etc.
        Then run morphological parse with ContentParser.
        """
        manager = SubtitleManager()
        success = manager.load_subtitles(subtitle_path)
        if not success:
            self.statusBar().showMessage(f"Could not parse subtitle: {subtitle_path}")
            return

        subs = manager.get_subtitles()  # list of { 'start_time': float, 'end_time': float, 'text': str }
        text_id = self.db.add_text_source(subtitle_path, "video_subtitle")

        cur = self.db._conn.cursor()
        for cue in subs:
            start_sec = cue["start_time"]
            end_sec = cue["end_time"]
            text_line = cue["text"]
            cur.execute("""
                INSERT INTO sentences (text_id, content, start_time, end_time)
                VALUES (?, ?, ?, ?)
            """, (text_id, text_line, start_sec, end_sec))
        self.db._conn.commit()

        # Morph parse
        parser = ContentParser()
        cur.execute("SELECT sentence_id, content FROM sentences WHERE text_id = ?", (text_id,))
        rows = cur.fetchall()
        for sentence_id, content in rows:
            tokens = parser.parse_content(content)
            for tk in tokens:
                dict_form_id = self.db.get_or_create_dictionary_form(
                    base_form=tk["base_form"],
                    reading=tk["reading"],
                    pos=tk["pos"]
                )
                self.db.add_surface_form(
                    dict_form_id=dict_form_id,
                    surface_form=tk["surface_form"],
                    reading=tk["reading"],
                    pos=tk["pos"],
                    sentence_id=sentence_id,
                    card_id=None,
                    parse_kanji=False
                )
            self.update_unknown_count_for_sentence(sentence_id)

    def update_unknown_count_for_sentence(self, sentence_id):
        cur = self.db._conn.cursor()
        update_query = """
        UPDATE sentences
        SET unknown_dictionary_form_count = (
            SELECT COUNT(DISTINCT df.dict_form_id)
            FROM dictionary_forms df
            JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
            JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
            WHERE sfs.sentence_id = sentences.sentence_id
              AND df.known = 0
        )
        WHERE sentence_id = ?;
        """
        cur.execute(update_query, (sentence_id,))
        self.db._conn.commit()

    def create_media_browser_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        # Left Frame: QTreeWidget
        left_frame = QFrame()
        left_frame.setFrameShape(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_frame)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Folder / File"])
        self.tree_widget.itemClicked.connect(self.on_tree_item_clicked)
        self.tree_widget.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        left_layout.addWidget(self.tree_widget)

        # Right Frame: details
        right_frame = QFrame()
        right_frame.setFrameShape(QFrame.StyledPanel)
        right_layout = QVBoxLayout(right_frame)

        self.detail_image_label = QLabel("No Image")
        self.detail_image_label.setStyleSheet("border: 1px solid gray;")
        self.detail_image_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.detail_image_label)

        self.detail_label = QLabel("No item selected")
        self.detail_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(self.detail_label)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        right_layout.addWidget(self.detail_text)

        self.btn_action1 = QPushButton("Action 1")
        self.btn_action1.clicked.connect(self.perform_action1)
        right_layout.addWidget(self.btn_action1)

        self.btn_action2 = QPushButton("Action 2")
        self.btn_action2.clicked.connect(self.perform_action2)
        right_layout.addWidget(self.btn_action2)

        # Spacer
        right_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        layout.addWidget(left_frame, 3)
        layout.addWidget(right_frame, 4)
        self.load_all_sources_as_relative_trees()
        return page

    def on_tree_item_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if data:
            data_type, db_id = data[0], data[1]  # might be folder or media_file
            self.update_detail_panel(data_type, db_id)
        else:
            self.detail_label.setText(item.text(0))
            self.detail_text.setText("No extra data for this item.")

    def on_tree_item_double_clicked(self, item, column):
        """
        Called when the user double-clicks an item in the tree.
        We'll do the same logic as perform_action1 if it's a video/media file.
        """
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        data_type = data[0]
        media_id = data[1]

        # Check if it's a video or media file
        if data_type in ("video", "media_file"):
            info = self.db.get_media_info(media_id)
            if not info:
                self.statusBar().showMessage("No media info found in DB.")
                return

            mpv_uri = info["mpv_path"]
            self.open_video_tab(mpv_uri, media_id)

    def update_detail_panel(self, data_type, db_id):
        if data_type == "source":
            self.show_source_details(db_id)
            self.btn_action1.setText("Action 1")
            self.btn_action2.setText("Action 2")
        elif data_type == "subdir":
            self.show_subdirectory_details(db_id)
            self.btn_action1.setText("Action 1")
            self.btn_action2.setText("Action 2")
        elif data_type == "video":
            self.detail_label.setText(f"Video File ID: {db_id}")
            self.detail_text.setText("A sample video file. Click 'Play' to watch.")
            self.btn_action1.setText("Play")
            self.btn_action2.setText("Action 2")
        elif data_type == "folder":
            self.detail_label.setText(f"Folder: {db_id}")
            self.detail_text.setText("Folder node from the pseudo explorer.")
        elif data_type == "media_file":
            self.detail_label.setText(f"Media ID: {db_id}")
            self.btn_action1.setText("Play")
            self.btn_action2.setText("Edit Metadata")

            # 1) fetch from DB
            info = self.db.get_media_info(db_id)
            if not info:
                # If no data, just show empty
                self.detail_text.setText("This media entry wasn't found in DB.")
                self.detail_image_label.setText("No image")
                return

            # 2) show the file_path
            lines = []
            lines.append(f"File Path: {info['file_path']}")
            lines.append(f"Type: {info['type'] or ''}")

            # 3) show the description if present
            if info["description"]:
                lines.append(f"Description:\n{info['description']}")
            else:
                lines.append("No description yet.")

            # 4) put all that text in the detail_text box
            self.detail_text.setText("\n".join(lines))

            # 5) set the image if a thumbnail path is available
            thumb_path = info["thumbnail_path"]
            if thumb_path and os.path.exists(thumb_path):
                from PyQt5.QtGui import QPixmap
                pixmap = QPixmap(thumb_path)
                self.detail_image_label.setPixmap(pixmap)
            else:
                self.detail_image_label.clear()
                self.detail_image_label.setText("No image")

    def populate_study_filter_combo(self):
        """
        Clears and repopulates the study_filter_combo with:
        - "All"
        - plus each distinct type in the 'texts' table.
        """
        self.study_filter_combo.clear()
        self.study_filter_combo.addItem("All")  # Always have an 'All' option

        cur = self.db._conn.cursor()
        cur.execute("SELECT DISTINCT type FROM texts ORDER BY type")
        rows = cur.fetchall()
        for (text_type,) in rows:
            # text_type could be None if any row has a NULL type; skip or handle carefully
            if text_type:
                self.study_filter_combo.addItem(text_type)

    def build_tree_items(self, parent_item, tree_level):
        """
        Recursively populate a QTreeWidgetItem from 'tree_level',
        a nested dict built by build_relative_directory_tree(...).
        """
        for key, value in tree_level.items():
            if key == "__files__":
                for (full_path, media_id) in value:
                    filename = os.path.basename(full_path)
                    file_item = QTreeWidgetItem([filename])
                    file_item.setData(0, Qt.UserRole, ("media_file", media_id, full_path))
                    parent_item.addChild(file_item)
            else:
                # 'key' is a subfolder
                folder_item = QTreeWidgetItem([key])
                folder_item.setData(0, Qt.UserRole, ("folder", key))
                parent_item.addChild(folder_item)
                self.build_tree_items(folder_item, value)

    def load_directory_tree_for_source(self, source_folder: str):
        """
        Clears the tree and shows just the media under `source_folder`.
        The top-level node text becomes the final part of the folder (e.g. 'Test').
        """
        self.tree_widget.clear()

        # 1) Gather all media that physically resides under this source folder
        cur = self.db._conn.cursor()
        # We'll just fetch all media, then filter those that start with source_folder:
        all_media = cur.execute("SELECT media_id, file_path FROM media").fetchall()

        relevant_rows = []
        # Normalize for consistent comparisons
        base_norm = os.path.normpath(source_folder).lower()
        for (m_id, fpath) in all_media:
            f_norm = os.path.normpath(fpath).lower()
            if f_norm.startswith(base_norm):
                # Keep original case version of fpath for display
                relevant_rows.append((m_id, fpath))

        # 2) Build a nested dict from those relevant rows
        # (Removed the "from main import ..." line; we call our local function directly)
        dir_tree = build_relative_directory_tree(relevant_rows, source_folder)

        # 3) The top-level node label
        top_text = os.path.basename(os.path.normpath(source_folder)) or source_folder
        top_item = QTreeWidgetItem([top_text])
        top_item.setData(0, Qt.UserRole, ("folder", source_folder))
        self.tree_widget.addTopLevelItem(top_item)

        # 4) Recursively add subfolders/files
        self.build_tree_items(top_item, dir_tree)

        self.statusBar().showMessage(f"Loaded media tree for: {source_folder}")

    def perform_action1(self):
        item = self.tree_widget.currentItem()
        if not item:
            return

        data = item.data(0, Qt.UserRole)
        if not data:
            return

        data_type = data[0]
        media_id = data[1]
        logger.info(f"Action 1 triggered on {data_type} with ID {media_id}")
        if data_type in ("video", "media_file"):
            logger.info(f"Play media {media_id}")
            info = self.db.get_media_info(media_id)
            logger.info(f"Play media {media_id} => {info['file_path']} Found")
            if not info:
                self.statusBar().showMessage("No media info found in DB.")
                return

            # Either pass raw OS path or mpv_path depending on your design:
            logger.info(f"Play media {media_id} => {info['file_path']} file path")
            mpv_uri = info["mpv_path"]
            logger.info(f"Play media {media_id} => {mpv_uri} mpv uri")
            self.open_video_tab(mpv_uri, media_id)
        else:
            self.statusBar().showMessage("Action 1 triggered (non-video).")

    def edit_metadata(self, media_id: int):
        """Open a dialog to manually edit metadata for the selected episode."""
        info = self.db.get_media_info(media_id)
        if not info:
            QMessageBox.warning(self, "Error", "No media info found in DB.")
            return

        file_stem = Path(info["file_path"]).stem
        show, season, episode = parse_filename_for_show_episode(file_stem)
        dialog = MetadataEditDialog(show, season, episode, self)
        if dialog.exec_() == QDialog.Accepted:
            show, season, episode = dialog.get_values()
            metadata_utils.fetch_and_store_metadata(media_id, show, season, episode)
            self.update_detail_panel("media_file", media_id)

    def perform_action2(self):
        item = self.tree_widget.currentItem()
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        data_type = data[0]
        if data_type == "media_file":
            media_id = data[1]
            self.edit_metadata(media_id)
        else:
            self.statusBar().showMessage("Performed Action 2 on the selected item.")

    def add_source_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Root Folder")
        if not folder_path:
            self.statusBar().showMessage("Add source folder canceled.")
            return

        source_id = self.db.add_source_folder(folder_path)
        self.cleanup_missing_files()
        self.walk_and_index(folder_path)

        # Now rebuild the entire multi-source tree
        self.load_all_sources_as_relative_trees()

        self.statusBar().showMessage(f"Source folder added/updated: {folder_path}")

    def rescan_all_sources(self):
        sources = self.db.get_all_sources()
        logger.info(f"Re-scanning {len(sources)} source folders...")

        if not sources:
            self.statusBar().showMessage("No source folders found in DB. Nothing to re-scan.")
            return

        self.cleanup_missing_files()

        # FIX: use "root_path" below
        for src in sources:
            folder_path = src["root_path"]  # now matches get_all_sources()
            self.walk_and_index(folder_path)

        self.load_all_sources_as_relative_trees()
        self.statusBar().showMessage("Re-scan of all sources completed.")

    def show_source_details(self, source_id: int):
        self.detail_label.setText(f"Source Folder ID: {source_id}")
        self.detail_text.setText(f"Metadata for the root source folder (ID = {source_id}).")

    def show_subdirectory_details(self, subdir_id: int):
        self.detail_label.setText(f"Subdirectory ID: {subdir_id}")
        self.detail_text.setText(f"Details for subdirectory ID = {subdir_id}.")

        ##########################################################################
        # Replace old single "Video Player" page with a multi-tab system
        ##########################################################################
    def create_video_tabs_page(self) -> QWidget:
        """
        A page that holds a QTabWidget for multiple mpv-based players.
        Each new video => a new tab with MyVideoPlayerWidget.
        """
        page = QWidget()
        layout = QVBoxLayout(page)

        self.video_tab_widget = QTabWidget()
        self.video_tab_widget.setTabsClosable(True)
        self.video_tab_widget.setMovable(True)
        self.video_tab_widget.tabCloseRequested.connect(self.close_video_tab)
        self.video_tab_widget.currentChanged.connect(self.on_video_tab_changed)

        layout.addWidget(self.video_tab_widget)
        return page

    def on_video_tab_changed(self, new_index: int):
        """
        Called whenever the user clicks a different video tab.
        If the subtitle window is open, re-fetch new lines.
        """
        if self.subtitle_window and self.subtitle_window.isVisible():
            self.update_subtitle_window()

    def close_video_tab(self, index: int):
        w = self.video_tab_widget.widget(index)
        if w:
            # Ensure the mpv player is actually shut down
            if hasattr(w, "player"):
                # Either of these approaches will tell MPV to end:
                w.player.terminate()  # 1) often used if available
                # OR
                # w.player.command("quit")      # 2) direct mpv command
                # OR
                # w.player.shutdown()           # 3) if older mpv bindings
            w.deleteLater()

        self.video_tab_widget.removeTab(index)

    def open_video_tab(self, mpv_uri: str, media_id: int):
        logger.info(f"Opening video tab for: {mpv_uri}")
        player_widget = MyVideoPlayerWidget(mpv_uri, self.db, media_id=media_id)
        # Connect that signal to a central slot
        player_widget.playbackTimeChanged.connect(self.on_player_time_changed)
        player_widget.openSubtitleWindowRequested.connect(self.open_subtitle_window)

        tab_title = os.path.basename(mpv_uri)  # or a nicer label
        self.video_tab_widget.addTab(player_widget, tab_title)

        self.video_tab_widget.setCurrentWidget(player_widget)

        index_of_new = self.video_tab_widget.indexOf(player_widget)
        logger.info("Index of new tab is %s", index_of_new)
        logger.info("Current tab is now %s", self.video_tab_widget.currentIndex())

        self.open_subtitle_window()

        self.set_main_page(2)
        self.statusBar().showMessage(f"Playing: {mpv_uri}")

    def on_player_time_changed(self, current_time: float):
        # Identify which MyVideoPlayerWidget fired the signal
        player_widget = self.sender()

        # If this widget is not the one in the active tab, just ignore it
        if player_widget != self.video_tab_widget.currentWidget():
            return

        # Otherwise, proceed
        if self.subtitle_window and self.subtitle_window.isVisible():
            self.subtitle_window.highlight_current_time(current_time)

    def open_subtitle_window(self):
        # If we haven't made one yet, create it
        logger.info("Opening subtitle window...")
        if not self.subtitle_window:
            self.subtitle_window = SubtitleWindow(
                parent=self,
                db_manager=self.db,
                anki_connector=self.anki,
                google_credentials=self.google_credentials,
                anki_media_path=self.anki_media_path,
                audio_player=self.audio_player,
                openai_api_key=self.openai_api_key,  # pass the key along
                tmdb_api_key=self.tmdb_api_key,
            )
            # Connect the signal here
            self.subtitle_window.subtitleDoubleClicked.connect(self.jump_to_time)
            self.subtitle_window.openVideoAtTime.connect(self.on_openVideoAtTime)
            self.subtitle_window.editorBackToSubtitles.connect(self.update_subtitle_window)
            self.subtitle_window.pausePlayRequested.connect(self.on_pausePlayRequested)
            # Track selection changes in the subtitle list
            self.subtitle_window.list_widget.currentRowChanged.connect(self.on_subtitle_selected)


        # If it's already created but closed, we can re-show it:
        if not self.subtitle_window.isVisible():
            self.subtitle_window.show()

        # Now load the correct subtitles for whichever video tab is currently selected
        self.update_subtitle_window()

    def on_pausePlayRequested(self):
        """
        Called whenever SubtitleWindow emits pausePlayRequested.
        We'll toggle the pause state on the currently active MPV tab.
        """
        mpv_player = self.get_active_mpv_player()  # your existing helper
        if mpv_player:
            mpv_player.pause = not mpv_player.pause
            logger.info("Toggled mpv pause state via pausePlayRequested signal.")
        else:
            logger.warning("No active mpv player to pause/play.")

    def on_openVideoAtTime(self, media_id: int, start_time: float):
        # Just call the standard open_video_tab
        logger.info(f"Opening video tab for media_id {media_id} at time {start_time}")
        info = self.db.get_media_info(media_id)
        mpv_uri = info["mpv_path"]
        logger.info(f"Opening video tab for: {mpv_uri}")
        self.open_video_tab(mpv_uri, media_id)
        logger.info("Seeking to start time...")
        # Then seek
        i = self.video_tab_widget.currentIndex()
        player_widget = self.video_tab_widget.widget(i)
        if player_widget and hasattr(player_widget, 'player'):
            QTimer.singleShot(2000, lambda: player_widget.player.seek(start_time, reference="absolute", precision="exact"))
            logger.info("Seeking done.")

    def update_subtitle_window(self):
        """
        Re-fetch the subtitles for the *currently selected video tab*,
        then call .set_subtitles(...) on the subtitle_window.
        """
        logger.info("Updating subtitle window...")
        if not self.subtitle_window:
            logger.info("Subtitle window not created yet.")
            return  # Window not created

        current_index = self.video_tab_widget.currentIndex()
        logger.info(f"Current tab index: {current_index}")
        if current_index < 0:
            # No tabs open
            logger.info("No video tabs open.")
            self.subtitle_window.set_subtitles([])
            return

        player_widget = self.video_tab_widget.widget(current_index)
        if not hasattr(player_widget, "media_id") or player_widget.media_id is None:
            # Can't load subtitles if we don't have a valid media_id
            logger.info("No media_id available for current video tab.")
            self.subtitle_window.set_subtitles([])
            return

        media_id = player_widget.media_id
        logger.info(f"Updating subtitle window for media_id {media_id}")

        # --- Query the DB for those lines (ordered by start_time)
        query = """
        SELECT s.sentence_id, s.start_time, s.end_time, s.content
          FROM sentences s
          JOIN texts t ON s.text_id = t.text_id
          JOIN subtitles sub ON sub.subtitle_file = t.source
         WHERE sub.media_id = ?
         ORDER BY s.start_time
        """
        cur = self.db._conn.cursor()
        cur.execute(query, (media_id,))
        rows = cur.fetchall()

        logger.info(f"Found {len(rows)} subtitle lines for media_id {media_id}")

        # Convert them to a list of (start, end, text)
        subtitle_lines = []
        self._subtitle_lines = []
        for (sid, start, end, text) in rows:
            subtitle_lines.append((start or 0.0, end or 0.0, text or ""))
            self._subtitle_lines.append((sid, text or ""))

        # Update the open SubtitleWindow
        logger.info("Updating subtitle window with new lines.")
        self.subtitle_window.set_subtitles(subtitle_lines)

    def on_subtitle_selected(self, index: int):
        if index < 0 or index >= len(self._subtitle_lines):
            return
        sentence_id, subtitle_text = self._subtitle_lines[index]
        # now pass the ID instead of the raw text
        if self.subtitle_window:
            self.subtitle_window.display_words_for_anki_editor(sentence_id)

    ##########################################################################
    # Page 2: Anki Manager
    ##########################################################################
    def create_anki_manager_page(self) -> QWidget:
        page = QWidget()
        main_layout = QHBoxLayout(page)

        ##################################################
        # LEFT SIDE: Deck List + Filter + Card List
        ##################################################
        left_layout = QVBoxLayout()

        # Anki Deck List
        self.anki_deck_list = QListWidget()
        self.anki_deck_list.itemClicked.connect(self.on_anki_deck_clicked)
        left_layout.addWidget(QLabel("Decks:"))
        left_layout.addWidget(self.anki_deck_list)

        # Filter for cards
        filter_layout = QHBoxLayout()
        self.anki_filter_edit = QLineEdit()
        self.anki_filter_edit.setPlaceholderText("Filter by native word...")
        self.anki_filter_edit.textChanged.connect(self.on_anki_filter_changed)
        filter_layout.addWidget(self.anki_filter_edit)
        left_layout.addLayout(filter_layout)

        # Card List
        self.anki_card_list = QListWidget()
        self.anki_card_list.itemClicked.connect(self.on_anki_card_clicked)
        left_layout.addWidget(QLabel("Cards:"))
        left_layout.addWidget(self.anki_card_list, stretch=1)

        main_layout.addLayout(left_layout, stretch=1)

        ##################################################
        # RIGHT SIDE: Deck Controls + "Deck Editor" Fields
        ##################################################
        right_side_layout = QVBoxLayout()

        # (1) "Deck Controls" group - you already had these buttons
        deck_controls_group = QGroupBox("Deck Controls")
        deck_controls_layout = QHBoxLayout(deck_controls_group)

        btn_import = QPushButton("Import into System")
        btn_import.clicked.connect(self.on_import_deck_clicked)
        deck_controls_layout.addWidget(btn_import)

        btn_unload = QPushButton("Unload Deck")
        btn_unload.clicked.connect(self.on_unload_deck_clicked)
        deck_controls_layout.addWidget(btn_unload)

        btn_generate = QPushButton("Generate Missing Resources")
        btn_generate.clicked.connect(self.on_generate_missing_resources_clicked)
        deck_controls_layout.addWidget(btn_generate)

        right_side_layout.addWidget(deck_controls_group)

        # (2) Card Details (Deck Editor style)
        card_details_group = QGroupBox("Card Details (Deck Editor)")
        form_layout = QFormLayout(card_details_group)

        # -- Basic fields --
        self.anki_field_card_id = QLineEdit()
        self.anki_field_card_id.setReadOnly(True)
        form_layout.addRow("Card ID:", self.anki_field_card_id)

        self.field_native_word = QLineEdit()
        form_layout.addRow("Native Word:", self.field_native_word)

        self.field_translated_word = QLineEdit()
        form_layout.addRow("Translated Word:", self.field_translated_word)

        self.field_pos = QLineEdit()
        form_layout.addRow("POS:", self.field_pos)

        self.field_reading = QLineEdit()
        form_layout.addRow("Reading:", self.field_reading)

        self.field_native_sentence = QPlainTextEdit()
        self.field_native_sentence.setFixedHeight(60)
        form_layout.addRow("Native Sentence:", self.field_native_sentence)

        self.field_translated_sentence = QPlainTextEdit()
        self.field_translated_sentence.setFixedHeight(60)
        form_layout.addRow("Translated Sentence:", self.field_translated_sentence)

        # -- Word Audio Field --
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

        # -- Sentence Audio Field --
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

        # -- Image Field --
        image_layout = QVBoxLayout()
        self.anki_image_label = QLabel()
        self.anki_image_label.setFixedSize(200, 200)
        self.anki_image_label.setStyleSheet("border: 1px solid gray;")
        self.anki_image_label.setScaledContents(True)
        image_layout.addWidget(self.anki_image_label)

        btn_regen_image = QPushButton("Regen Image")
        btn_regen_image.clicked.connect(self.regen_image)
        image_layout.addWidget(btn_regen_image)

        form_layout.addRow("Sentence Image:", image_layout)

        # Spacer
        form_layout.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))

        right_side_layout.addWidget(card_details_group, stretch=1)

        # Put all into main_layout
        right_container = QWidget()
        right_container.setLayout(right_side_layout)
        main_layout.addWidget(right_container, stretch=1)

        return page

    def on_anki_deck_clicked(self, item: QListWidgetItem):
        deck_name = item.text().strip()
        if deck_name:
            self.load_anki_cards_for_deck(deck_name)

    def load_anki_cards_for_deck(self, deck_name: str):
        self.anki_card_list.clear()
        # Example DB call: get all cards with a certain deck_name
        self.current_deck_cards = self.db.get_cards_by_local_deck_name(deck_name)

        filter_text = self.anki_filter_edit.text().strip().lower()
        for card in self.current_deck_cards:
            native_word = card.get("native_word", "").lower()
            if filter_text in native_word:
                display_text = f"[{card['card_id']}] {card['native_word']}"
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, card)
                self.anki_card_list.addItem(item)

    def load_all_cards(self):
        self.anki_card_list.clear()
        self.current_deck_cards = self.db.get_all_cards()  # new method that returns everything
        for card in self.current_deck_cards:
            display_text = f"[{card['card_id']}] {card['native_word']}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, card)
            self.anki_card_list.addItem(item)

    def on_anki_filter_changed(self, text: str):
        current_deck_item = self.anki_deck_list.currentItem()
        if current_deck_item:
            deck_name = current_deck_item.text().strip()
            self.load_anki_cards_for_deck(deck_name)

    def on_anki_card_clicked(self, item: QListWidgetItem):
        card_data = item.data(Qt.UserRole)
        if card_data:
            self.populate_deck_editor_fields(card_data)

    def populate_deck_editor_fields(self, card_data: dict):
        self.current_card_data = card_data

        self.anki_field_card_id.setText(str(card_data.get("card_id", "")))
        self.field_native_word.setText(card_data.get("native_word", ""))
        self.field_translated_word.setText(card_data.get("translated_word", ""))
        self.field_pos.setText(card_data.get("pos", ""))
        self.field_reading.setText(card_data.get("reading", ""))
        self.field_native_sentence.setPlainText(card_data.get("native_sentence", ""))
        self.field_translated_sentence.setPlainText(card_data.get("translated_sentence", ""))
        self.field_word_audio.setText(card_data.get("word_audio", ""))
        self.field_sentence_audio.setText(card_data.get("sentence_audio", ""))

        # Load or preview the <img src="filename">
        self.load_image_from_html(card_data.get("image", ""))

    def load_image_from_html(self, image_html: str):
        if not image_html.strip():
            self.anki_image_label.setText("[No Image]")
            return
        match = re.search(r'<img\s+src="([^"]+)"', image_html)
        if not match:
            self.anki_image_label.setText("[Invalid <img>]")
            return

        filename = match.group(1)
        image_path = os.path.join(self.anki_media_path, filename)
        if os.path.exists(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                scaled = pix.scaled(self.anki_image_label.width(),
                                    self.anki_image_label.height(),
                                    Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
                self.anki_image_label.setPixmap(scaled)
            else:
                self.anki_image_label.setText("[Invalid Image Data]")
        else:
            self.anki_image_label.setText("[Image Not Found]")

    def play_word_audio(self):
        text = self.field_word_audio.text().strip()
        self.play_audio_tag(text)

    def play_sentence_audio(self):
        text = self.field_sentence_audio.text().strip()
        self.play_audio_tag(text)

    def play_audio_tag(self, audio_tag: str):
        match = re.search(r'\[sound:(.*?)\]', audio_tag)
        if not match:
            logger.info("No [sound:filename] found.")
            return
        filename = match.group(1)
        full_path = os.path.join(self.anki_media_path, filename)
        if not os.path.exists(full_path):
            logger.info(f"Audio file not found: {full_path}")
            return
        logger.info(f"Playing audio: {full_path}")
        self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(full_path)))
        self.audio_player.play()

    def regen_word_audio(self):
        if not self.current_card_data:
            return

        native_word = self.field_native_word.text().strip()
        if not native_word:
            logger.info("No native_word => cannot regen audio.")
            return

        card_id = self.current_card_data["card_id"]

        # Google TTS Setup
        if not os.path.exists(self.google_credentials):
            logger.info("Missing google_credentials_json => cannot TTS.")
            return
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials

        try:
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=native_word)
            voice = texttospeech.VoiceSelectionParams(language_code="ja-JP",
                                                      ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = client.synthesize_speech(input=synthesis_input,
                                                voice=voice,
                                                audio_config=audio_config)

            audio_filename = f"word_audio_{uuid.uuid4().hex}.mp3"
            b64_data = base64.b64encode(response.audio_content).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                logger.info("Could not store TTS in Anki.")
                return

            new_tag = f"[sound:{audio_filename}]"

            # Update DB
            self.db.update_card_audio(card_id, "word", new_tag)

            # Update UI fields
            self.field_word_audio.setText(new_tag)
            self.current_card_data["word_audio"] = new_tag

            # Update Anki note field if needed
            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "word audio", new_tag)

            logger.info("Regenerated word audio => %s", new_tag)

        except Exception as e:
            logger.exception("Error regenerating word audio: %s", e)

    def regen_sentence_audio(self):
        if not self.current_card_data:
            return

        native_sentence = self.field_native_sentence.toPlainText().strip()
        if not native_sentence:
            logger.info("No native_sentence => cannot regen audio.")
            return

        card_id = self.current_card_data["card_id"]

        if not os.path.exists(self.google_credentials):
            logger.info("Missing google_credentials_json => cannot TTS.")
            return
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials

        try:
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=native_sentence)
            voice = texttospeech.VoiceSelectionParams(language_code="ja-JP",
                                                      ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            audio_filename = f"sentence_audio_{uuid.uuid4().hex}.mp3"
            b64_data = base64.b64encode(response.audio_content).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                logger.info("Failed to store audio in Anki.")
                return

            new_tag = f"[sound:{audio_filename}]"

            self.db.update_card_audio(card_id, "sentence", new_tag)
            self.field_sentence_audio.setText(new_tag)
            self.current_card_data["sentence_audio"] = new_tag

            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "sentence audio", new_tag)

            logger.info("Regenerated sentence audio => %s", new_tag)

        except Exception as e:
            logger.exception("Error regenerating sentence audio: %s", e)

    def regen_image(self):
        if not self.current_card_data:
            return

        native_sentence = self.field_native_sentence.toPlainText().strip()
        if not native_sentence:
            logger.info("No native sentence => cannot generate image.")
            return

        card_id = self.current_card_data["card_id"]

        if not self.openai_api_key:
            logger.info("No OpenAI_API_Key => cannot call DALL·E.")
            return
        openai.api_key = self.openai_api_key

        try:
            prompt = f"Illustration for the sentence: '{native_sentence}'"
            response = openai.Image.create(prompt=prompt, n=1, size="1024x1024", model="dall-e-3")
            image_url = response["data"][0]["url"]
            image_data = requests.get(image_url).content

            image_filename = f"sentence_image_{uuid.uuid4().hex}.png"
            b64_data = base64.b64encode(image_data).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
            if res is None:
                logger.info("Failed to store image in Anki.")
                return

            new_img_html = f'<img src="{image_filename}">'

            self.db.update_card_image(card_id, new_img_html)
            self.current_card_data["image"] = new_img_html
            self.load_image_from_html(new_img_html)

            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "image", new_img_html)

            logger.info("Regenerated image => %s", new_img_html)

        except Exception as e:
            logger.exception("Error regenerating image: %s", e)

    def on_import_deck_clicked(self):
        """
        Imports the currently selected Anki deck into the local system,
        replicating the legacy import_anki_deck logic with the DeckFieldMappingDialog.
        """

        # 1) Ensure the user has selected a deck from anki_deck_list
        current_item = self.anki_deck_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Deck Selected", "Please select a deck from the list.")
            return

        selected_deck = current_item.text().strip()
        if not selected_deck:
            QMessageBox.warning(self, "Invalid Deck Name", "The selected deck name is empty or invalid.")
            return



        logger.info(f"Importing deck '{selected_deck}' into system...")

        # 2) Verify deck in Anki
        all_decks = self.anki.get_decks()
        if isinstance(all_decks, dict):
            deck_names = all_decks.keys()
        else:
            deck_names = all_decks

        if selected_deck not in deck_names:
            QMessageBox.warning(self, "Deck Not Found", f"'{selected_deck}' was not found in Anki.")
            return

        # 3) Find card IDs
        card_ids = self.anki.find_cards(f'deck:"{selected_deck}"')
        logger.info(f"Found {len(card_ids)} cards in '{selected_deck}'")

        if not card_ids:
            QMessageBox.warning(self, "No Cards Found", f"No cards in '{selected_deck}' deck.")
            return

        # 4) Determine the model name from the first card
        first_card_info = self.anki.get_card_info([card_ids[0]])
        if not first_card_info or "modelName" not in first_card_info[0]:
            QMessageBox.warning(self, "Anki Model Error", "Could not determine the model of the selected deck.")
            return

        model_name = first_card_info[0]["modelName"]
        logger.info(f"Deck '{selected_deck}' uses model: {model_name}")

        # 5) Retrieve the model's field names from Anki
        anki_fields = self.anki.invoke("modelFieldNames", modelName=model_name)
        logger.info(f"modelFieldNames => {anki_fields}")
        if not anki_fields:
            QMessageBox.warning(self, "Model Fields Error", "Could not retrieve fields for the deck's model.")
            return

        # 6) Load stored mappings from config (if any)
        stored_mappings = self.load_field_mappings(model_name)  # <= your old method
        logger.info(f"Stored mappings for '{model_name}': {stored_mappings}")

        mappings = {}

        # 7) Check if stored mappings exist/are valid
        #    We want to ensure all anki_fields are in stored_mappings or at least handle them gracefully.
        #    Or we can simply prompt user to confirm re-using them.
        if stored_mappings and all(f in anki_fields for f in stored_mappings.keys()):
            use_stored = QMessageBox.question(
                self,
                "Use Previous Mappings?",
                "Previous field mappings found for this model. Use them?",
                QMessageBox.Yes | QMessageBox.No
            )
            if use_stored == QMessageBox.Yes:
                mappings = stored_mappings
            else:
                # 8) Show DeckFieldMappingDialog for user to define them
                dialog = DeckFieldMappingDialog(anki_fields, self)
                if dialog.exec_() == QDialog.Accepted:
                    mappings = dialog.get_mappings()
                    # Save new mappings to config
                    self.save_field_mappings(model_name, mappings)
                else:
                    self.statusBar().showMessage("Import canceled (field mapping dialog closed).")
                    return
        else:
            # 8a) If no stored mappings, pop up the DeckFieldMappingDialog
            dialog = DeckFieldMappingDialog(anki_fields, self)
            if dialog.exec_() == QDialog.Accepted:
                mappings = dialog.get_mappings()
                self.save_field_mappings(model_name, mappings)
            else:
                self.statusBar().showMessage("Deck import canceled by user.")
                return

        # 9) Possibly verify that important fields ("native word", "native sentence", etc.) are mapped
        required_app_fields = ["native word", "native sentence", "translated word", "translated sentence"]
        # Reverse the dictionary: anki_field => app_field
        # But you might just check if each of these appears in mappings.values()
        mapped_local_fields = set(mappings.values())
        for req_field in required_app_fields:
            if req_field not in mapped_local_fields:
                QMessageBox.warning(self, "Missing Field",
                                    f"The required field '{req_field}' is not mapped.")
                return

        # 10) Actually extract the data using the final mappings
        cards_data = self.extract_card_data_from_anki(selected_deck, mappings)
        logger.info(f"extract_card_data_from_anki => extracted {len(cards_data)} items.")

        if not cards_data:
            QMessageBox.warning(self, "Error", "No cards found or extracted data is empty.")
            return

        # 11) (Optional) Missing images/audio
        #     Same logic as in your old code:
        if any(not card.get("image") or not card["image"].get("value", "").strip() for card in cards_data):
            resp = QMessageBox.question(self, "Generate Images",
                                        "Some cards have no sentence image. Generate them with DALL·E?",
                                        QMessageBox.Yes | QMessageBox.No)
            if resp == QMessageBox.Yes:
                self.generate_missing_sentence_images(cards_data, self.config_path)

        if any(
                (not c.get("sentence audio") or not c["sentence audio"].get("value", "").strip()) or
                (not c.get("word audio") or not c["word audio"].get("value", "").strip())
                for c in cards_data
        ):
            resp = QMessageBox.question(self, "Generate Audio",
                                        "Some cards are missing audio. Generate them via TTS?",
                                        QMessageBox.Yes | QMessageBox.No)
            if resp == QMessageBox.Yes:
                self.generate_missing_audio(cards_data, self.config_path)

        # 12) Ensure local Words/Study deck exist
        self.ensure_core_decks_exist()

        # 13) Insert the card data into the local DB (mirroring old code)
        self.insert_imported_cards_into_db(cards_data)

        # 11) *NEW*: Move the original Anki deck under "Managed::"
        #     (i.e. rename "Core 2k" => "Managed::Core 2k")
        new_subdeck = f"Managed::{selected_deck}"
        self.anki.invoke("createDeck", deck=new_subdeck)  # ensure "Managed::" deck structure
        self.anki.invoke("changeDeck", cards=card_ids, deck=new_subdeck)

        try:
            self.anki.invoke("deleteDecks", decks=[selected_deck], cardsToo=False)
            logger.info(f"Deleted old deck '{selected_deck}' after moving its cards.")
        except Exception as e:
            logger.warning(f"Could not delete deck '{selected_deck}': {e}")

        self.statusBar().showMessage(f"Imported deck '{selected_deck}' into the system.")
        logger.info(f"'{selected_deck}' successfully imported with user-defined mappings.")

    def extract_card_data_from_anki(self, selected_deck, mappings):
        cards = self.anki.find_cards(f'deck:"{selected_deck}"')
        if not cards:
            return []
        cards_data = []
        for card_id in cards:
            card_info = self.anki.get_card_info([card_id])
            if not card_info or "fields" not in card_info[0]:
                continue

            fields = card_info[0]["fields"]
            card_data = {}
            for anki_field, app_field in mappings.items():
                if app_field is None:
                    continue
                card_data[app_field] = fields.get(anki_field, "")

            card_data["deck_name"] = selected_deck
            cards_data.append(card_data)

        return cards_data

    def load_field_mappings(self, model_name: str) -> dict:
        logger.info(f"Loading field mappings for model: {model_name}")

        # We already read self.config in ensure_config, so no need to re-read the file
        if (self.config.has_section("FIELD_MAPPINGS") and
                self.config.has_option("FIELD_MAPPINGS", model_name)):
            mappings_json = self.config.get("FIELD_MAPPINGS", model_name)
            logger.info(f"Loaded mappings JSON: {mappings_json}")
            try:
                return json.loads(mappings_json)
            except json.JSONDecodeError:
                return {}
        return {}

    def save_field_mappings(self, model_name: str, mappings: dict):
        logger.info(f"Saving field mappings for model: {model_name}")
        if not self.config.has_section("FIELD_MAPPINGS"):
            self.config.add_section("FIELD_MAPPINGS")
        self.config.set("FIELD_MAPPINGS", model_name, json.dumps(mappings))

        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)
        logger.info("Field mappings saved.")

    def ensure_core_decks_exist(self):
        # 1) Ensure 'Words' deck in local DB
        words_deck_id = self.db.ensure_Words_deck_exists()
        # 2) Also ensure 'Words' in Anki
        res_words = self.anki.invoke("createDeck", deck="Words")
        if res_words is None:
            QMessageBox.warning(self, "Anki Error", "Could not ensure 'Words' deck in Anki.")
            return

        # 3) Ensure 'Study' deck in local DB
        study_deck_id = self.db.ensure_Study_exists()
        # 4) Also ensure 'Study' in Anki
        res_study = self.anki.invoke("createDeck", deck="Study")
        if res_study is None:
            QMessageBox.warning(self, "Anki Error", "Could not ensure 'Study' deck in Anki.")
            return

    def insert_imported_cards_into_db(self, cards_data: list):
        """
        Insert each card dict from cards_data into the local DB,
        performing morphological parse, etc., exactly like the old code.
        Also adds a new note in Anki's 'Words' deck for each card.
        """
        if not cards_data:
            return

        from content_parser import ContentParser
        parser = ContentParser()

        # 1) Suppose we want them in "Words" deck by default (local DB).
        words_deck_id = self.db.get_deck_id_by_name("Words") or self.db.ensure_Words_deck_exists()

        for card in cards_data:
            logger.info("Processing final note creation for card: %s", card)

            # 2) Extract each field from the 'card' dictionary
            #    The old code expects each mapped field to be a dict { "value": "..." }
            #    so we do .get("value", "").strip().
            native_word_str = card.get("native word", {}).get("value", "").strip()
            native_sentence_str = card.get("native sentence", {}).get("value", "").strip()
            translated_word_str = card.get("translated word", {}).get("value", "").strip()
            translated_sentence_str = card.get("translated sentence", {}).get("value", "").strip()
            reading_str = card.get("reading", {}).get("value", "").strip()
            pos_value = card.get("pos", {}).get("value", "").strip()
            word_audio_value = card.get("word audio", {}).get("value", "").strip()
            sentence_audio_value = card.get("sentence audio", {}).get("value", "").strip()
            image_html = card.get("image", {}).get("value", "").strip()

            # 3) Build an HTML <img> tag if you had an extracted 'src'
            #    (In the old code, you do something like `image = f'<img src="{image_src}">'`)
            #    We'll assume `image_html` already has it, or is empty if no image.

            deck_name = card.get("deck_name", "ImportedDeck")  # e.g. 'Core 2k' or 'JLPT N5' etc.
            tags = ["anki_deck", deck_name]  # old code uses these tags

            # 4) Construct the note_type_fields exactly like the old code:
            #    This means your Anki model has fields named "native word", "translated word", etc.
            note_type_fields = {
                "native word": native_word_str,
                "translated word": translated_word_str,
                "word audio": word_audio_value,
                "pos": pos_value,
                "native sentence": native_sentence_str,
                "translated sentence": translated_sentence_str,
                "sentence audio": sentence_audio_value,
                "image": image_html,  # e.g. '<img src="..." />'
                "reading": reading_str
            }

            # 5) Add the note to Anki in the "Words" deck, using the "CSRS" model
            note_id = self.anki.add_note("Words", "CSRS", note_type_fields, tags=tags)
            if note_id is None:
                logger.warning("Could not add note to Anki for card: %s", card)
                continue

            # 6) Retrieve the brand-new Anki card_id from that note
            card_ids = self.anki.find_cards(f"nid:{note_id}")
            if not card_ids:
                logger.warning("No card_ids found for newly created note_id: %s", note_id)
                continue

            anki_card_id = card_ids[0]  # typically there's just one in a basic note

            # 7) Insert local DB row for this "card"
            text_id = self.db.add_text_source(deck_name, "anki_import")
            sentence_id = self.db.add_sentence_if_not_exist(text_id, native_sentence_str)

            card_id = self.db.add_card(
                deck_id=words_deck_id,
                anki_card_id=anki_card_id,  # link to the newly created note
                deck_origin=deck_name,
                native_word=native_word_str,
                translated_word=translated_word_str,
                word_audio=word_audio_value,
                pos=pos_value,
                native_sentence=native_sentence_str,
                translated_sentence=translated_sentence_str,
                sentence_audio=sentence_audio_value,
                image=image_html,
                reading=reading_str,
                sentence_id=sentence_id
            )

            # 8) Morphological parse of the sentence
            tokens = parser.parse_content(native_sentence_str)
            for tk in tokens:
                dict_form_id = self.db.get_or_create_dictionary_form(
                    base_form=tk["base_form"],
                    reading=tk["reading"],
                    pos=tk["pos"]
                )
                self.db.add_surface_form(
                    dict_form_id=dict_form_id,
                    surface_form=tk["surface_form"],
                    reading=tk["reading"],
                    pos=tk["pos"],
                    sentence_id=sentence_id,
                    card_id=card_id  # associate these forms with the new local card
                )

            # NEW: Update the unknown count once tokens are in place
            self.update_unknown_count_for_sentence(sentence_id)
            # 9) Tag the local card with the deck_name
            self.db.update_card_tags(card_id, [deck_name])


        logger.info(f"Done inserting {len(cards_data)} card(s) into local DB and Anki.")

    def on_unload_deck_clicked(self):
        self.statusBar().showMessage("Unload deck clicked (placeholder)")

    def on_generate_missing_resources_clicked(self):
        """
        Generate missing images (via DALL·E) and missing audio (via Google TTS)
        for *all* cards in the currently selected deck, without prompting.
        """
        deck_item = self.anki_deck_list.currentItem()
        if not deck_item:
            QMessageBox.information(self, "No Deck Selected",
                                    "Please select a deck from the list before mass-generating resources.")
            return

        deck_name = deck_item.text().strip()
        if not deck_name:
            QMessageBox.information(self, "Invalid Deck", "The selected deck name is empty.")
            return

        # 1) Fetch all local cards for this deck
        cards = self.db.get_cards_by_local_deck_name(deck_name)
        if not cards:
            QMessageBox.information(self, "No Cards", f"No local cards found in deck '{deck_name}'.")
            return

        missing_images = []
        missing_word_audio = []
        missing_sentence_audio = []

        # 2) Identify which cards have missing image/audio fields
        for c in cards:
            # If the "image" field is empty/None
            if not c.get("image", "").strip():
                missing_images.append(c)

            # If "word_audio" is empty/None
            if not c.get("word_audio", "").strip():
                missing_word_audio.append(c)

            # If "sentence_audio" is empty/None
            if not c.get("sentence_audio", "").strip():
                missing_sentence_audio.append(c)

        # 3) Generate Images for cards missing them
        if missing_images:
            self.statusBar().showMessage(f"Generating images for {len(missing_images)} card(s) in '{deck_name}'...")
            for card_data in missing_images:
                self.regen_image_for_card(card_data)
            self.statusBar().showMessage("Done generating images.")

        # 4) Generate Word Audio
        if missing_word_audio:
            self.statusBar().showMessage(f"Generating word audio for {len(missing_word_audio)} card(s)...")
            for card_data in missing_word_audio:
                self.regen_word_audio_for_card(card_data)
            self.statusBar().showMessage("Done generating word audio.")

        # 5) Generate Sentence Audio
        if missing_sentence_audio:
            self.statusBar().showMessage(f"Generating sentence audio for {len(missing_sentence_audio)} card(s)...")
            for card_data in missing_sentence_audio:
                self.regen_sentence_audio_for_card(card_data)
            self.statusBar().showMessage("Done generating sentence audio.")

        # Final status update
        self.statusBar().showMessage("All missing resources have been generated for this deck.")

    def regen_image_for_card(self, card_data: dict):
        """
        A helper that calls the same DALL·E logic you use in `regen_image()`,
        but for a specific card_data dictionary. This code is basically
        identical to your `regen_image()` method, but we pass in card_data
        instead of using self.current_card_data.
        """
        # 1) Extract the card_id and the sentence text
        card_id = card_data["card_id"]
        native_sentence = card_data.get("native_sentence", "").strip()
        if not native_sentence:
            logger.info("No native sentence => cannot generate image.")
            return

        if not self.openai_api_key:
            logger.info("No OpenAI API key => cannot call DALL·E.")
            return
        openai.api_key = self.openai_api_key

        try:
            prompt = f"Illustration for the sentence: '{native_sentence}'"
            response = openai.Image.create(prompt=prompt, n=1, size="1024x1024", model="dall-e-3")
            image_url = response["data"][0]["url"]
            image_data = requests.get(image_url).content

            image_filename = f"sentence_image_{uuid.uuid4().hex}.png"
            b64_data = base64.b64encode(image_data).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
            if res is None:
                logger.info("Failed to store image in Anki.")
                return

            new_img_html = f'<img src="{image_filename}">'

            # 2) Update local DB
            self.db.update_card_image(card_id, new_img_html)

            # 3) Update the local card data
            card_data["image"] = new_img_html

            # 4) If this card is currently selected in the UI, refresh the displayed image
            if self.current_card_data and self.current_card_data["card_id"] == card_id:
                self.load_image_from_html(new_img_html)

            # 5) Update the note field in Anki
            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "image", new_img_html)

            logger.info(f"Regen image => {new_img_html}")

        except Exception as e:
            logger.exception("Error regenerating image for card_id=%s: %s", card_id, e)

    def regen_word_audio_for_card(self, card_data: dict):
        """
        Same logic as 'regen_word_audio()' but for a specific card data dict.
        """
        card_id = card_data["card_id"]
        native_word = card_data.get("native_word", "").strip()
        if not native_word:
            logger.info("No native_word => cannot regen audio.")
            return

        if not os.path.exists(self.google_credentials):
            logger.info("Missing google_credentials_json => cannot TTS.")
            return
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials

        try:
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=native_word)
            voice = texttospeech.VoiceSelectionParams(language_code="ja-JP",
                                                      ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            audio_filename = f"word_audio_{uuid.uuid4().hex}.mp3"
            b64_data = base64.b64encode(response.audio_content).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                logger.info("Could not store TTS in Anki.")
                return

            new_tag = f"[sound:{audio_filename}]"

            self.db.update_card_audio(card_id, "word", new_tag)
            card_data["word_audio"] = new_tag

            # If it's the currently displayed card, refresh UI field
            if self.current_card_data and self.current_card_data["card_id"] == card_id:
                self.field_word_audio.setText(new_tag)

            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "word audio", new_tag)

            logger.info("Regen word audio => %s", new_tag)

        except Exception as e:
            logger.exception("Error regenerating word audio for card_id=%s: %s", card_id, e)

    def regen_sentence_audio_for_card(self, card_data: dict):
        """
        Same logic as 'regen_sentence_audio()' but for a specific card data dict.
        """
        card_id = card_data["card_id"]
        native_sentence = card_data.get("native_sentence", "").strip()
        if not native_sentence:
            logger.info("No native_sentence => cannot regen audio.")
            return

        if not os.path.exists(self.google_credentials):
            logger.info("Missing google_credentials_json => cannot TTS.")
            return
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials

        try:
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=native_sentence)
            voice = texttospeech.VoiceSelectionParams(language_code="ja-JP",
                                                      ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL)
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            audio_filename = f"sentence_audio_{uuid.uuid4().hex}.mp3"
            b64_data = base64.b64encode(response.audio_content).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                logger.info("Failed to store audio in Anki.")
                return

            new_tag = f"[sound:{audio_filename}]"

            self.db.update_card_audio(card_id, "sentence", new_tag)
            card_data["sentence_audio"] = new_tag

            # If it's the currently displayed card, refresh UI field
            if self.current_card_data and self.current_card_data["card_id"] == card_id:
                self.field_sentence_audio.setText(new_tag)

            anki_card_id = self.db.get_anki_card_id(card_id)
            if anki_card_id:
                self.db.update_anki_note_field(anki_card_id, "sentence audio", new_tag)

            logger.info("Regen sentence audio => %s", new_tag)

        except Exception as e:
            logger.exception("Error regenerating sentence audio for card_id=%s: %s", card_id, e)

    def load_anki_decks(self):
        self.anki_deck_list.clear()
        deck_names = self.db.get_anki_import_decks()  # placeholder
        for deck_name in deck_names:
            item = QListWidgetItem(deck_name)
            item.setData(Qt.UserRole, deck_name)
            self.anki_deck_list.addItem(item)

    def load_all_sources_as_relative_trees(self):
        """
        Clears self.tree_widget and shows each source folder as a top-level node.
        Under each source node, media files are shown with subfolders
        relative to that source's path.
        """
        logging.info("Loading all sources in relative mode...")
        self.tree_widget.clear()

        # 1) Get all sources
        logger.info("tree clear")
        sources = self.db.get_all_sources()
        logger.info("sources done")
        if not sources:
            self.statusBar().showMessage("No source folders found in the database.")
            return

        # 2) Fetch all media once
        cur = self.db._conn.cursor()
        all_media = cur.execute("SELECT media_id, file_path FROM media").fetchall()
        logger.info("all media done")

        # 3) For each source, filter & build a nested dict
        for src in sources:
            source_folder = src["root_path"]
            base_norm = os.path.normpath(source_folder).lower()
            logger.info(f"Processing source: {source_folder}")

            # Filter media that starts with this source_folder
            relevant_rows = []
            for (m_id, fpath) in all_media:
                f_norm = os.path.normpath(fpath).lower()
                if f_norm.startswith(base_norm):
                    relevant_rows.append((m_id, fpath))

            if not relevant_rows:
                # Optionally create an empty node if no media
                top_text = os.path.basename(os.path.normpath(source_folder)) or source_folder
                empty_item = QTreeWidgetItem([f"{top_text} (no media)"])
                empty_item.setData(0, Qt.UserRole, ("folder", source_folder))
                self.tree_widget.addTopLevelItem(empty_item)
                continue

            # Build the relative structure
            dir_tree = build_relative_directory_tree(relevant_rows, source_folder)
            logger.info(f"Built dir_tree for {source_folder}")
            # Top-level node name is e.g. 'Test'
            top_text = os.path.basename(os.path.normpath(source_folder)) or source_folder
            top_item = QTreeWidgetItem([top_text])
            top_item.setData(0, Qt.UserRole, ("folder", source_folder))
            self.tree_widget.addTopLevelItem(top_item)

            # Recurse
            self.build_tree_items(top_item, dir_tree)
        logger.info("All sources loaded in relative mode.")
        self.statusBar().showMessage("All sources loaded in relative mode.")



    def on_anki_filter_changed(self, text: str):
        current_deck_item = self.anki_deck_list.currentItem()
        if current_deck_item:
            deck_name = current_deck_item.data(Qt.UserRole)
            self.load_anki_cards_for_deck(deck_name)


    def populate_anki_card_fields(self, card_data: dict):
        self.anki_field_card_id.setText(str(card_data.get("card_id", "")))
        self.anki_field_title.setText(card_data.get("title", ""))
        self.anki_field_desc.setPlainText(card_data.get("description", ""))
        self.anki_field_audio.setText(card_data.get("audio", ""))

    def on_anki_play_audio(self):
        audio_path = self.anki_field_audio.text().strip()
        self.statusBar().showMessage(f"Playing audio: {audio_path}")

    def on_anki_regen_audio(self):
        self.statusBar().showMessage("Regenerating audio...")

    def on_anki_regen_image(self):
        self.statusBar().showMessage("Regenerating image...")

    def sync_anki(self):
        """
        1) Check AnkiConnect connection
        2) Ensure 'Words', 'Study', 'Kanji' decks exist in Anki (System Decks)
        3) Get list of 'Managed' (imported) deck names from DB
        4) Show everything in self.anki_deck_list, dividing them into sections:
           - =======System Decks=======
           - =======Managed Decks======
           - All the rest
        """
        logger.info("sync_anki() called - Starting Anki sync process")

        # 1) Check connection to AnkiConnect
        try:
            version = self.anki.invoke("version")
            logger.debug(f"AnkiConnect 'version' result: {version}")
            if version is None:
                raise ConnectionError("AnkiConnect did not return a valid response.")
        except Exception as e:
            logger.exception("Error while connecting to AnkiConnect")
            QMessageBox.warning(
                self,
                "Anki Connection Error",
                "Could not connect to Anki.\n"
                "Make sure Anki is running and AnkiConnect is installed.\n\n"
                f"Details: {e}"
            )
            return

        # 2) Ensure System Decks exist
        system_decks = ["Words", "Study", "Kanji", "Managed"]
        logger.debug("Retrieving current decks from Anki...")
        current_decks = self.anki.get_decks()  # could be dict or list
        logger.debug(f"Current decks: {current_decks}")

        if not current_decks:
            logger.warning("No decks found in Anki")
            QMessageBox.warning(self, "No Decks Found",
                                "Anki returned no decks. Possibly Anki isn't running, or no decks exist.")
            return

        # Convert current_decks to a list of names
        if isinstance(current_decks, dict):
            all_deck_names = list(current_decks.keys())
        else:
            all_deck_names = list(current_decks)

        # Create any missing system decks
        for deck_name in system_decks:
            if deck_name not in all_deck_names:
                logger.info(f"Deck '{deck_name}' not found. Attempting to create it...")
                create_result = self.anki.invoke("createDeck", deck=deck_name)
                logger.debug(f"createDeck('{deck_name}') => {create_result}")

                logger.info("Ensuring that 'Managed::' decks have new cards/day = 0.")

                # Gather a list of managed subdecks
                managed_decks = [dn for dn in all_deck_names if dn.startswith("Managed::")]

                if not managed_decks:
                    logger.debug("No 'Managed::' subdecks found; nothing to update.")
                    self.statusBar().showMessage("Anki sync complete. No Managed subdecks to update.")
                    return

                #  (A) Retrieve deck configurations for all Managed subdecks at once
                deck_configs_response = self.anki.invoke("deckConfigurations", decks=managed_decks)

                # The response is structured like:
                # {
                #   "decks": {
                #       "Managed::Foo": {"id": <overrideId or 0>, "maxTakenFrom": <configGroupId>},
                #       "Managed::Bar": {"id": <overrideId or 0>, "maxTakenFrom": <configGroupId>},
                #       ...
                #   },
                #   "configGroups": [...],
                #   "deckOverrides": [... possibly ...]
                # }

                # We'll hold onto some data for building an update request.
                deck_overrides_to_update = []
                config_groups = deck_configs_response.get("configGroups", [])
                deck_overrides = deck_configs_response.get("deckOverrides", [])

                # Build a quick dict for easy configGroups lookup by ID
                group_by_id = {}
                for cg in config_groups:
                    group_by_id[cg["id"]] = cg["config"]

                # Build a quick dict for deckOverride by ID
                override_by_id = {}
                for od in deck_overrides:
                    override_by_id[od["id"]] = od["config"]

                # Now iterate each "Managed::..." deck
                for dname in managed_decks:
                    deck_info = deck_configs_response["decks"][dname]
                    override_id = deck_info["id"]  # 0 => no override
                    parent_id = deck_info["maxTakenFrom"]

                    if override_id == 0:
                        # No override => copy the parent's entire config
                        parent_cfg = group_by_id.get(parent_id, {})
                        config_for_deck = parent_cfg.copy()  # shallow copy
                    else:
                        # We have an override => look it up
                        if override_id in override_by_id:
                            config_for_deck = override_by_id[override_id]
                        else:
                            # fallback
                            parent_cfg = group_by_id.get(parent_id, {})
                            config_for_deck = parent_cfg.copy()

                    # Now set new.perDay=0
                    if "new" not in config_for_deck:
                        config_for_deck["new"] = {}
                    config_for_deck["new"]["perDay"] = 0

                    # We'll push an update for this deck
                    deck_overrides_to_update.append({
                        "id": override_id,  # 0 => create new override
                        "deckName": dname,
                        "config": config_for_deck
                    })

                if deck_overrides_to_update:
                    # Build a single "updateDeckConfigs" request for all of them at once
                    update_request = {
                        "action": "updateDeckConfigs",
                        "version": 6,
                        "params": {
                            "configGroups": [],
                            "deckOverrides": deck_overrides_to_update
                        }
                    }
                    try:
                        self.anki._invoke(update_request)
                        logger.info(f"Set newCards/day=0 for these decks: {managed_decks}")
                        self.statusBar().showMessage("Anki sync complete. Managed decks updated to 0 new cards/day.")
                    except Exception as e:
                        logger.warning(f"Error updating deck configs: {e}")
                        self.statusBar().showMessage("Anki sync complete, but could not update Managed decks' config.")
                else:
                    logger.debug("No deck_overrides_to_update built; nothing to apply.")
                    self.statusBar().showMessage("Anki sync complete. No new overrides needed.")

                if create_result is None:
                    logger.warning(f"Failed to create '{deck_name}' in Anki.")
                    self.statusBar().showMessage(f"Failed to create '{deck_name}' deck in Anki.")
                else:
                    logger.info(f"Created missing deck: {deck_name}")
                    self.statusBar().showMessage(f"Created missing deck: {deck_name}")
                    # Also add it to our local list
                    all_deck_names.append(deck_name)

        # 3) Get 'Managed Decks' from your DB
        # (Adjust method name/logic depending on how you store "imported" deck names.)
        try:
            logger.debug("Fetching 'imported' deck names from the local DB (anki_import).")
            imported_decks = self.db.get_anki_import_decks()  # e.g. returns ["MyImportedDeck", "JLPTN5", ...]
            logger.debug(f"Imported deck names from DB: {imported_decks}")
        except Exception as e:
            logger.exception("Error while fetching imported decks from DB")
            imported_decks = []

        # Re-fetch from Anki after potential system deck creation
        updated_decks = self.anki.get_decks()
        if isinstance(updated_decks, dict):
            updated_list = list(updated_decks.keys())
        else:
            updated_list = list(updated_decks)
        all_deck_names = sorted(set(updated_list))  # remove duplicates, sort if you want

        # 4) Build sections:
        #    - system_decks (that are found)
        #    - managed_decks (found in DB)
        #    - everything else

        found_system = [d for d in system_decks if d in all_deck_names]
        found_managed = [d for d in imported_decks if d in all_deck_names and d not in found_system]
        # ^ exclude system decks from "managed" if they happen to also be in the DB
        other_decks = [
            d for d in all_deck_names
            if d not in found_system and d not in found_managed
        ]

        logger.info("Clearing the deck list widget to display final sections.")
        self.anki_deck_list.clear()

        # ========System Decks========
        if found_system:
            self.anki_deck_list.addItem("=======System Decks=======")
            for sd in found_system:
                self.anki_deck_list.addItem(sd)
            self.anki_deck_list.addItem("============")

        # ========Managed Decks========
        if found_managed:
            self.anki_deck_list.addItem("=======Managed Decks=======")
            for md in found_managed:
                self.anki_deck_list.addItem(md)
            self.anki_deck_list.addItem("============")

        # The rest
        for deck in other_decks:
            self.anki_deck_list.addItem(deck)

        self.statusBar().showMessage("Anki sync complete. Decks loaded.")
        #self.load_all_cards()
        logger.info("Anki sync complete. Decks loaded in the UI.")

    def update_coverage(self):
        self.statusBar().showMessage("Updating coverage... (placeholder)")

    def parse_pending_kanji(self):
        self.statusBar().showMessage("Parsing kanji...")
        self.db.parse_pending_kanji()
        self.statusBar().showMessage("Kanji parsing complete.")

    def on_parse_deferred_kanji_clicked(self):
        """Slot for the button on the Kanji study tab."""
        self.parse_pending_kanji()
        self.refresh_deferred_kanji_count()

    def refresh_deferred_kanji_count(self):
        """Update the label showing how many entries still need parsing."""
        count = self.db.count_deferred_kanji()
        if hasattr(self, "label_deferred_kanji"):
            self.label_deferred_kanji.setText(f"Deferred Kanji: {count}")

    ##########################################################################
    # Study Page
    ##########################################################################
    def create_study_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.study_stack = QStackedWidget()
        layout.addWidget(self.study_stack)

        self.page_study_explore = self.create_study_explore_page()
        self.page_study_set = self.create_study_set_material_page()
        self.page_study_cards = self.create_study_cards_page()
        self.page_study_kanji = self.create_study_kanji_page()

        self.study_stack.addWidget(self.page_study_explore)  # 0
        self.study_stack.addWidget(self.page_study_set)      # 1
        self.study_stack.addWidget(self.page_study_cards)    # 2
        self.study_stack.addWidget(self.page_study_kanji)    # 3

        self.study_stack.setCurrentWidget(self.page_study_set)
        return page

    def create_study_cards_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        stats_group = QGroupBox("Study / Deck Statistics")
        stats_layout = QVBoxLayout(stats_group)

        self.label_n_plus_one_count = QLabel("N+1 Cards in Words Deck: 0")
        stats_layout.addWidget(self.label_n_plus_one_count)

        self.label_study_deck_count = QLabel("Cards in Study Deck: 0")
        stats_layout.addWidget(self.label_study_deck_count)

        self.label_current_material_count = QLabel("Currently Studying Materials: 0")
        stats_layout.addWidget(self.label_current_material_count)

        self.label_average_comprehension = QLabel("Average Comprehension: 0.0%")
        stats_layout.addWidget(self.label_average_comprehension)

        # --- NEW CODE: Add a label for the "Predicted" result ---
        self.label_predicted_comprehension = QLabel("Predicted if +X Cards: 0.0% (Gain +0.0%)")
        stats_layout.addWidget(self.label_predicted_comprehension)
        # ---------------------------------------------------------

        stats_layout.addStretch()
        layout.addWidget(stats_group)

        # Existing spinbox + button row
        allocate_row = QHBoxLayout()
        allocate_row.addWidget(QLabel("Number of N+1 Cards to Allocate:"))
        self.n_plus_one_spin = QSpinBox()
        self.n_plus_one_spin.setRange(1, 999)
        self.n_plus_one_spin.setValue(10)
        allocate_row.addWidget(self.n_plus_one_spin)
        layout.addLayout(allocate_row)

        btn_allocate = QPushButton("Allocate N+1 Cards")
        btn_allocate.clicked.connect(self.on_allocate_n_plus_one_cards)
        layout.addWidget(btn_allocate)

        # --- NEW CODE: a button to show predicted comprehension ---
        btn_predict = QPushButton("Predict Comprehension for X new cards")
        btn_predict.clicked.connect(self.on_predict_comprehension_increase)
        layout.addWidget(btn_predict)
        # ----------------------------------------------------------

        layout.addStretch()
        self.refresh_cards_stats()
        return page

    # --------------
    #  NEW CODE
    # --------------
    def on_predict_comprehension_increase(self):
        """
        When user clicks 'Predict Comprehension for X new cards',
        compute the predicted average, then update the label.
        """
        X = self.n_plus_one_spin.value()
        predicted_avg, delta = self.predict_comprehension_increase_for_X_cards(X)
        if abs(delta) < 0.0001:
            # No improvement or no available cards
            self.label_predicted_comprehension.setText("No improvement (0%)")
        else:
            self.label_predicted_comprehension.setText(
                f"Predicted if +{X} cards: {predicted_avg:.1f}% (Gain +{delta:.1f}%)"
            )

    def refresh_cards_stats(self):
        """
        Gathers updated counts/statistics from the DB and populates the
        labels on the Study → Cards page (N+1 count, Study deck count, etc.),
        as well as comprehension stats for currently-studying texts.
        """

        # 1) How many 'N+1' cards exist in 'Words' deck?
        #    N+1 is typically: unknown_dictionary_form_count <= 1
        words_deck_id = self.db.get_deck_id_by_name("Words")
        n_plus_one_count = 0
        if words_deck_id:
            cur = self.db._conn.cursor()
            query = """
                SELECT COUNT(c.card_id)
                  FROM cards c
                  JOIN sentences s ON c.sentence_id = s.sentence_id
                 WHERE c.deck_id = ?
                   AND s.unknown_dictionary_form_count <= 1
            """
            cur.execute(query, (words_deck_id,))
            row = cur.fetchone()
            n_plus_one_count = row[0] if row else 0

        # 2) How many cards are currently in the 'Study' deck?
        study_deck_id = self.db.get_deck_id_by_name("Study")
        study_deck_count = 0
        if study_deck_id:
            cur = self.db._conn.cursor()
            cur.execute("SELECT COUNT(*) FROM cards WHERE deck_id = ?", (study_deck_id,))
            row = cur.fetchone()
            study_deck_count = row[0] if row else 0

        # 3) Currently Studying materials?
        #    e.g. texts WHERE studying=1
        cur = self.db._conn.cursor()
        cur.execute("SELECT COUNT(*), AVG(comprehension_percentage) FROM texts WHERE studying=1")
        row = cur.fetchone()
        if row:
            current_material_count = row[0] or 0
            average_comprehension = row[1] or 0.0
        else:
            current_material_count = 0
            average_comprehension = 0.0

        # 4) Update the labels
        self.label_n_plus_one_count.setText(f"N+1 Cards in Words Deck: {n_plus_one_count}")
        self.label_study_deck_count.setText(f"Cards in Study Deck: {study_deck_count}")
        self.label_current_material_count.setText(f"Currently Studying Materials: {current_material_count}")
        self.label_average_comprehension.setText(f"Average Comprehension: {average_comprehension:.1f}%")

        # If you want to do something fancy like:
        #   "50.0% (2 of 4 unknown forms left)" you'd need more queries
        # but this covers the basic idea.

    def on_allocate_n_plus_one_cards(self):
        """
        Moves from the 'Words' deck to the 'Study' deck a limited number
        of N+1 cards (i.e. unknown_dictionary_form_count <= 1),
        based on the user's chosen spin box value.
        """
        words_deck_id = self.db.get_deck_id_by_name("Words")
        study_deck_id = self.db.get_deck_id_by_name("Study")
        if not words_deck_id or not study_deck_id:
            self.statusBar().showMessage("Either 'Words' or 'Study' deck is missing in the local DB.")
            return

        # How many cards does the user want to move?
        number_to_move = self.n_plus_one_spin.value()

        # 1) Gather N+1 card_ids in 'Words'
        cur = self.db._conn.cursor()
        query = """
            SELECT c.card_id
              FROM cards c
              JOIN sentences s ON c.sentence_id = s.sentence_id
             WHERE c.deck_id = ?
               AND s.unknown_dictionary_form_count <= 1
             LIMIT ?
        """
        cur.execute(query, (words_deck_id, number_to_move))
        rows = cur.fetchall()
        if not rows:
            self.statusBar().showMessage("No N+1 cards found in 'Words' (or already moved).")
            return

        card_ids = [r[0] for r in rows]

        # 2) Move them to 'Study' in DB + Anki
        self.db.move_cards_to_deck("Study", card_ids)

        # 3) Refresh stats to show updated counts
        self.refresh_cards_stats()

        # 4) Let the user know
        self.statusBar().showMessage(
            f"Moved {len(card_ids)} N+1 card(s) from 'Words' to 'Study'."
        )

    # -------------------------------------------------
    #  NEW CODE: In-memory comprehension predictions
    # -------------------------------------------------
    def compute_average_comprehension_for_studying_texts(self, known_forms_set):
        """
        Computes the average comprehension across all texts WHERE studying=1,
        given a set of known dict_form_ids (in memory).

        We'll do a direct DB query for each text to see how many of its forms
        are in `known_forms_set`.
        """
        cur = self.db._conn.cursor()
        # 1) Get all studying=1 text_ids
        cur.execute("SELECT text_id FROM texts WHERE studying=1")
        studying_texts = [row[0] for row in cur.fetchall()]
        if not studying_texts:
            return (100.0, 0)  # or (0.0, 0), up to you

        total_percent = 0.0
        for tid in studying_texts:
            # All distinct forms in this text
            cur.execute("""
                SELECT DISTINCT df.dict_form_id
                  FROM dictionary_forms df
                  JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
                  JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
                  JOIN sentences s ON s.sentence_id = sfs.sentence_id
                 WHERE s.text_id = ?
            """, (tid,))
            forms_in_text = [r[0] for r in cur.fetchall()]
            if not forms_in_text:
                total_percent += 100.0
                continue

            known_count = sum(1 for f in forms_in_text if f in known_forms_set)
            percent = (known_count / len(forms_in_text)) * 100.0
            total_percent += percent

        avg_percent = total_percent / len(studying_texts)
        return (avg_percent, len(studying_texts))

    def compute_card_incremental_improvement(self, card_id, known_forms_set, baseline):
        """
        If we 'learn' this card (i.e. mark its unknown forms known),
        how much would the average comprehension go up from `baseline`?

        Returns a float (the delta in percentage).
        """
        # Which forms are currently unknown for this card?
        unknowns = self.db.get_unknown_dict_forms_from_card(card_id)
        if not unknowns:
            return 0.0  # no improvement

        # pretend we know them now
        temp_known = known_forms_set.union(unknowns)

        new_avg, _ = self.compute_average_comprehension_for_studying_texts(temp_known)
        return new_avg - baseline

    def predict_comprehension_increase_for_X_cards(self, X):
        """
        Greedily pick up to X 'N+1' cards from 'Words' deck that yield
        the best incremental improvements in comprehension. Return (final_avg, delta).
        """
        words_deck_id = self.db.get_deck_id_by_name("Words")
        if not words_deck_id:
            return (0.0, 0.0)

        # Identify N+1 cards (example: unknown_dictionary_form_count <= 1)
        cur = self.db._conn.cursor()
        cur.execute("""
            SELECT c.card_id
              FROM cards c
              JOIN sentences s ON c.sentence_id = s.sentence_id
             WHERE c.deck_id = ?
               AND s.unknown_dictionary_form_count <= 1
        """, (words_deck_id,))
        candidate_cards = [row[0] for row in cur.fetchall()]
        if not candidate_cards:
            return (0.0, 0.0)

        # Current known forms from DB
        cur.execute("SELECT dict_form_id FROM dictionary_forms WHERE known=1")
        known_forms_set = set(r[0] for r in cur.fetchall())

        # Baseline average
        baseline_avg, _ = self.compute_average_comprehension_for_studying_texts(known_forms_set)
        current_avg = baseline_avg

        chosen = []
        for _ in range(X):
            best_card = None
            best_improv = 0.0
            for card_id in candidate_cards:
                inc = self.compute_card_incremental_improvement(card_id, known_forms_set, current_avg)
                if inc > best_improv:
                    best_improv = inc
                    best_card = card_id

            if (not best_card) or (best_improv <= 0.0):
                break

            # "Learn" that card => update local set
            new_unknowns = self.db.get_unknown_dict_forms_from_card(best_card)
            known_forms_set.update(new_unknowns)
            chosen.append(best_card)
            # recalc new average
            new_avg, _ = self.compute_average_comprehension_for_studying_texts(known_forms_set)
            current_avg = new_avg
            candidate_cards.remove(best_card)

        final_avg = current_avg
        delta = final_avg - baseline_avg
        return (final_avg, delta)

    def on_predict_new_comprehension_clicked(self):
        X = self.n_plus_one_spin.value()  # e.g. the spinbox for how many new cards
        predicted_avg, delta = self.predict_comprehension_increase_for_X_cards(self.db, X)

        # Suppose your label_average_comprehension is the old baseline.
        # We can either show “(new) => predicted_avg%” or
        # show “+X% improvement”, etc.
        msg = (
            f"Current Average: {self.label_average_comprehension.text()}\n"
            f"Predicted New Average (adding {X} cards): {predicted_avg:.1f}%\n"
            f"Gain: +{delta:.1f}%"
        )
        QMessageBox.information(self, "Predicted Comprehension", msg)

    def create_study_kanji_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.label_deferred_kanji = QLabel("Deferred Kanji: 0")
        layout.addWidget(self.label_deferred_kanji)

        btn_parse = QPushButton("Parse Deferred Kanji")
        btn_parse.clicked.connect(self.on_parse_deferred_kanji_clicked)
        layout.addWidget(btn_parse)

        layout.addStretch()
        self.refresh_deferred_kanji_count()
        return page

    def create_study_explore_page(self) -> QWidget:
        page = QWidget()
        main_layout = QVBoxLayout(page)

        # 1) Sentence indicator (optional label)
        self.sentence_indicator = QLabel("Random Sentence")
        self.sentence_indicator.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.sentence_indicator)

        # 2) Image label
        self.image_label = QLabel("[No Image]")
        self.image_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.image_label)

        # 3) Sentence label
        self.sentence_label = QLabel("(No sentence loaded yet)")
        self.sentence_label.setAlignment(Qt.AlignCenter)
        self.sentence_label.setWordWrap(True)
        # Increase font size if desired
        sentence_font = self.sentence_label.font()
        sentence_font.setPointSize(sentence_font.pointSize() * 2)
        self.sentence_label.setFont(sentence_font)
        main_layout.addWidget(self.sentence_label)

        # 4) Scroll area for the words (unchanged)
        self.words_scroll = QScrollArea()
        self.words_scroll.setWidgetResizable(True)
        words_container = QWidget()
        self.words_layout = QHBoxLayout(words_container)
        self.words_layout.setAlignment(Qt.AlignCenter)
        self.words_scroll.setWidget(words_container)
        main_layout.addWidget(self.words_scroll)

        # 5) Bottom row: Put both Replay and Next Sentence side by side
        bottom_layout = QHBoxLayout()
        bottom_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.btn_replay_audio = QPushButton("Replay Audio")
        self.btn_replay_audio.clicked.connect(self.replay_audio_explore)
        bottom_layout.addWidget(self.btn_replay_audio)

        self.btn_next_sentence = QPushButton("Next Sentence")
        self.btn_next_sentence.clicked.connect(self.load_random_sentence_explore)
        bottom_layout.addWidget(self.btn_next_sentence)

        bottom_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        main_layout.addLayout(bottom_layout)

        # 6) Initialize with a random sentence
        #self.load_random_sentence_explore()

        return page

    ########################################
    # Explore Tab Helper Methods
    ########################################

    def load_random_sentence_explore(self):
        """
        Fetches a random sentence from DB, sets self.explore_sentence_id & text,
        then calls load_media_explore + load_surface_forms_explore, and finally auto-plays audio.
        """
        sentence_data = self.db.get_random_sentence()
        if not sentence_data:
            # If no sentences, clear display
            self.explore_sentence_id = None
            self.explore_sentence_text = None
            self.sentence_label.setText("No sentences found in the database.")
            self.image_label.setText("[No Image]")
            self.clear_words_layout_explore()
            return

        self.explore_sentence_id, self.explore_sentence_text = sentence_data
        self.sentence_label.setText(self.explore_sentence_text or "")

        # Load image/audio for the card (if any)
        self.load_media_explore()

        # Load words for this sentence
        self.load_surface_forms_explore()

        # AUTO-PLAY: If we have a valid audio file, play it now
        if self.explore_current_audio_file:
            self.replay_audio_explore()

        self.statusBar().showMessage("Loaded a new random sentence.")

    def load_media_explore(self):
        """
        Retrieves card info for the current sentence (image/audio),
        parses out the image file path and [sound:filename], etc.
        """
        if not self.explore_sentence_id:
            self.image_label.setText("[No Image]")
            self.explore_current_audio_file = None
            return

        card_data = self.db.get_card_by_sentence_id(self.explore_sentence_id)
        if not card_data:
            # If no card, set blank
            self.image_label.setText("[No Image]")
            self.explore_current_audio_file = None
            return

        sentence_audio, image_html = card_data  # (sentence_audio, image_html)

        # Parse the audio
        self.explore_current_audio_file = None
        if sentence_audio:
            match = re.search(r'\[sound:(.*?)\]', sentence_audio)
            if match:
                audio_filename = match.group(1)
                audio_path = os.path.join(self.anki_media_path, audio_filename)
                if os.path.exists(audio_path):
                    self.explore_current_audio_file = audio_path
                else:
                    self.statusBar().showMessage(f"Audio file not found: {audio_path}")

        # Parse the image
        image_path = None
        if image_html:
            match_img = re.search(r'<img\s+src="([^"]+)"', image_html)
            if match_img:
                image_filename = match_img.group(1)
                temp_path = os.path.join(self.anki_media_path, image_filename)
                if os.path.exists(temp_path):
                    image_path = temp_path
                else:
                    self.statusBar().showMessage(f"Image file not found: {temp_path}")

        # Display the image (or no image)
        if image_path:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pix = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled_pix)
            else:
                self.image_label.setText("[Invalid image data]")
        else:
            self.image_label.setText("[No Image]")

    def load_surface_forms_explore(self):
        """
        Fetches all surface forms/dict forms for the current sentence,
        displays them as word widgets with "Known?" checkboxes.
        """
        if not self.explore_sentence_id:
            self.clear_words_layout_explore()
            return

        forms = self.db.get_surface_forms_for_sentence(self.explore_sentence_id)
        self.clear_words_layout_explore()  # remove old items
        self.explore_checkboxes = {}

        # If no forms found, display a single label
        if not forms:
            no_words_label = QLabel("No words found in this sentence.")
            no_words_label.setAlignment(Qt.AlignCenter)
            word_font = no_words_label.font()
            word_font.setPointSize(word_font.pointSize() * 2)
            no_words_label.setFont(word_font)
            self.words_layout.addWidget(no_words_label)
            return

        # Build a bigger font for the words
        word_font = QFont()
        word_font.setPointSize(word_font.pointSize() * 2)

        # Each row in `forms` is: (surface_form_id, surface_form, dict_form_id, base_form, known_flag)
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
            # Connect the stateChanged to update the DB
            # We use a little lambda to pass the dict_form_id
            word_checkbox.stateChanged.connect(
                lambda state, d_id=df_id: self.on_explore_checkbox_toggled(d_id, state)
            )

            word_layout.addWidget(word_label)
            word_layout.addWidget(dict_form_label)
            word_layout.addWidget(word_checkbox)
            word_layout.setAlignment(Qt.AlignHCenter)

            self.words_layout.addWidget(word_container)

            # Track the checkbox in a dict, if you want to reference later
            self.explore_checkboxes[df_id] = word_checkbox

    def on_explore_checkbox_toggled(self, dict_form_id, state):
        """
        Called when user toggles "Known?" for a dictionary form in the Explore tab.
        Updates DB: dictionary_forms.known=1 (or 0).
        Then re-counts unknown forms in all relevant sentences.
        """
        known = (state == Qt.Checked)
        self.db.set_dictionary_form_known(dict_form_id, known)
        self.db.update_unknown_counts_for_dict_form(dict_form_id)
        self.statusBar().showMessage("Dictionary form known status updated.")

    def replay_audio_explore(self):
        """
        Called when user clicks 'Replay Audio' in Explore tab.
        Plays the current audio file if available.
        """
        if self.explore_current_audio_file and os.path.exists(self.explore_current_audio_file):
            self.statusBar().showMessage("Playing audio...")
            self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(self.explore_current_audio_file)))
            self.audio_player.play()
        else:
            self.statusBar().showMessage("No audio file available to play.")

    def clear_words_layout_explore(self):
        """
        Removes all widgets from the self.words_layout.
        """
        for i in reversed(range(self.words_layout.count())):
            item = self.words_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def populate_placeholder_words(self):
        word_font = QFont()
        word_font.setPointSize(word_font.pointSize() * 2)

        dummy_words = ["Lorem", "Ipsum", "Dolor", "Sit", "Amet"]
        for w in dummy_words:
            word_container = QWidget()
            word_layout = QVBoxLayout(word_container)

            word_label = QLabel(w)
            word_label.setAlignment(Qt.AlignCenter)
            word_label.setFont(word_font)

            dict_form_label = QLabel("(dictForm)")
            dict_form_label.setAlignment(Qt.AlignCenter)
            dict_form_label.setFont(word_font)

            word_checkbox = QCheckBox("Known?")
            word_checkbox.setFont(word_font)

            word_layout.addWidget(word_label)
            word_layout.addWidget(dict_form_label)
            word_layout.addWidget(word_checkbox)
            word_layout.setAlignment(Qt.AlignHCenter)

            self.words_layout.addWidget(word_container)

    def on_replay_audio_clicked_placeholder(self):
        print("Replay Audio clicked (placeholder)")

    def on_next_sentence_clicked_placeholder(self):
        print("Next Sentence clicked (placeholder)")
        self.sentence_label.setText("Another sample sentence (placeholder).")

    def create_study_upload_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel("Upload Target Study Text"))
        btn_upload = QPushButton("Select File...")
        btn_upload.clicked.connect(self.upload_study_text)
        layout.addWidget(btn_upload)

        return page

    def upload_study_text(self):
        self.statusBar().showMessage("Uploading study text... (placeholder)")

    def create_study_set_material_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by Media Type:"))
        self.study_filter_combo = QComboBox()
        self.study_filter_combo.addItems(["All", "Video", "Audio", "Text"])
        self.study_filter_combo.currentIndexChanged.connect(self.on_study_filter_changed)
        filter_layout.addWidget(self.study_filter_combo)
        layout.addLayout(filter_layout)

        lists_layout = QHBoxLayout()
        current_layout = QVBoxLayout()
        current_layout.addWidget(QLabel("Current Materials (Comprehension %)"))

        self.list_current_material = QListWidget()
        self.list_current_material.itemClicked.connect(self.on_current_material_clicked)
        current_layout.addWidget(self.list_current_material)

        btn_add_to_db = QPushButton("Add to Database")
        btn_add_to_db.clicked.connect(self.on_add_to_db_clicked)
        current_layout.addWidget(btn_add_to_db)

        # NEW BUTTON: "Update Comprehension"
        btn_update_comprehension = QPushButton("Update Comprehension")
        btn_update_comprehension.clicked.connect(self.on_update_comprehension_clicked)
        current_layout.addWidget(btn_update_comprehension)

        lists_layout.addLayout(current_layout)

        arrow_layout = QVBoxLayout()
        btn_arrow_left = QPushButton("<--")
        btn_arrow_left.clicked.connect(self.on_arrow_left_clicked)
        arrow_layout.addWidget(btn_arrow_left)

        btn_arrow_right = QPushButton("-->")
        btn_arrow_right.clicked.connect(self.on_arrow_right_clicked)
        arrow_layout.addWidget(btn_arrow_right)
        lists_layout.addLayout(arrow_layout)

        studying_layout = QVBoxLayout()
        studying_layout.addWidget(QLabel("Currently Studying"))
        self.list_suggested_material = QListWidget()
        self.list_suggested_material.itemClicked.connect(self.on_suggested_material_clicked)
        studying_layout.addWidget(self.list_suggested_material)

        lists_layout.addLayout(studying_layout)
        layout.addLayout(lists_layout)

        return page

    def get_active_mpv_player(self):
        # Access the currently selected tab in self.video_tab_widget
        current_index = self.video_tab_widget.currentIndex()
        if current_index < 0:
            return None

        player_widget = self.video_tab_widget.widget(current_index)
        if not player_widget or not hasattr(player_widget, "player"):
            return None

        return player_widget.player  # This is an mpv.MPV instance

    def on_update_comprehension_clicked(self):
        """
        1) Recompute comprehension_percentage for every text in the DB.
        2) Re-rank each dictionary_form based on its total frequency
           *only in texts that have studying=1*.
        3) Reload the study materials list(s) so the user sees any changes.
        """
        # 1) Update each text’s comprehension
        cur = self.db._conn.cursor()
        cur.execute("SELECT text_id FROM texts")
        all_text_ids = [row[0] for row in cur.fetchall()]

        for tid in all_text_ids:
            self.db.update_text_comprehension(tid)

        # 2) Update dictionary form rankings based on the *studying=1* texts
        self.db.update_dictionary_form_rankings()

        # 3) Reload the left/right lists
        self.load_study_materials()

        self.statusBar().showMessage("Comprehension updated and dictionary forms re-ranked.")

    def on_add_to_db_clicked(self):
        # 1) Let user pick one or more .txt files
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Text Files",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        if not files:
            self.statusBar().showMessage("No files selected.")
            return

        # 2) Process each file
        for file_path in files:
            self.index_text_file(file_path)

        # 3) Reload or refresh whichever lists show the texts
        self.load_study_materials()

        self.statusBar().showMessage("Finished adding text files to the database.")

    def index_text_file(self, text_path: str):
        """
        Treat the .txt file at text_path as a 'text' source.
        Insert it into 'texts', parse each line into 'sentences',
        then morphologically parse with self.parser.
        """
        import os

        # 1) Add an entry in 'texts' with type='text'
        text_id = self.db.add_text_source(text_path, "text")

        # 2) Read lines from the file
        if not os.path.exists(text_path):
            self.statusBar().showMessage(f"File not found: {text_path}")
            return

        with open(text_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        cur = self.db._conn.cursor()

        # 3) Insert each line into 'sentences'
        for line in lines:
            line = line.strip()
            if not line:
                continue
            cur.execute("""
                INSERT INTO sentences (text_id, content)
                VALUES (?, ?)
            """, (text_id, line))

        self.db._conn.commit()

        # 4) Morphological parse
        #    Retrieve the newly inserted sentences for this text
        cur.execute("SELECT sentence_id, content FROM sentences WHERE text_id = ?", (text_id,))
        rows = cur.fetchall()

        for sentence_id, content in rows:
            tokens = self.parser.parse_content(content)  # same approach you use in subtitles
            for tk in tokens:
                dict_form_id = self.db.get_or_create_dictionary_form(
                    base_form=tk["base_form"],
                    reading=tk["reading"],
                    pos=tk["pos"]
                )
                self.db.add_surface_form(
                    dict_form_id=dict_form_id,
                    surface_form=tk["surface_form"],
                    reading=tk["reading"],
                    pos=tk["pos"],
                    sentence_id=sentence_id,
                    card_id=None
                )
            # update unknown forms count
            self.update_unknown_count_for_sentence(sentence_id)

        self.statusBar().showMessage(f"Imported text file: {text_path}")

    def on_arrow_right_clicked(self):
        # Move the selected item from list_current_material -> list_suggested_material
        item = self.list_current_material.currentItem()
        if not item:
            return

        text_id = item.data(Qt.UserRole)
        if text_id:
            # Mark as studying
            self.db.set_text_studying(text_id, True)

        # Remove from left list, add to right list
        row = self.list_current_material.row(item)
        self.list_current_material.takeItem(row)
        self.list_suggested_material.addItem(item)

        self.statusBar().showMessage(f"Text {text_id} set to studying=True")

    def on_arrow_left_clicked(self):
        # Move the selected item from list_suggested_material -> list_current_material
        item = self.list_suggested_material.currentItem()
        if not item:
            return

        text_id = item.data(Qt.UserRole)
        if text_id:
            # Mark as not studying
            self.db.set_text_studying(text_id, False)

        row = self.list_suggested_material.row(item)
        self.list_suggested_material.takeItem(row)
        self.list_current_material.addItem(item)

        self.statusBar().showMessage(f"Text {text_id} set to studying=False")



    def on_study_filter_changed(self, index: int):
        pass

    def on_current_material_clicked(self, item: QListWidgetItem):
        pass

    def on_suggested_material_clicked(self, item: QListWidgetItem):
        pass

    def load_study_materials(self):
        """
        Based on the currently selected type in study_filter_combo:
          - list_current_material shows texts with studying=0
          - list_suggested_material shows texts with studying=1
        If 'All' is chosen, we ignore the type filter entirely.
        """
        self.list_current_material.clear()
        self.list_suggested_material.clear()

        # 1) Figure out the user's chosen type
        chosen_filter = self.study_filter_combo.currentText()

        # 2) Build two SQL queries:
        #    - one for items "not studying" (studying=0)
        #    - one for items "studying" (studying=1)
        #    If chosen_filter != "All", we add "AND type=?" to each query.

        sql_not_studying = "SELECT text_id, source FROM texts WHERE studying=0"
        sql_studying = "SELECT text_id, source FROM texts WHERE studying=1"
        params = []

        if chosen_filter != "All":
            sql_not_studying += " AND type=?"
            sql_studying += " AND type=?"
            params = [chosen_filter]

        sql_not_studying += " ORDER BY text_id"
        sql_studying += " ORDER BY text_id"

        # 3) Execute the queries
        cur = self.db._conn.cursor()

        # -- Not Studying --
        cur.execute(sql_not_studying, params)
        rows_false = cur.fetchall()
        for (text_id, source_path) in rows_false:

            comprehension = self.db.get_text_comprehension(text_id)  # e.g. fetch from DB
            if comprehension is None:
                comp_str = "N/A"
            else:
                comp_str = f"{comprehension:.1f}%"

            display_text = f"[ID={text_id}] {os.path.basename(source_path)}  (Comp: {comp_str})"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, text_id)
            self.list_current_material.addItem(item)

        # -- Currently Studying --
        cur.execute(sql_studying, params)
        rows_true = cur.fetchall()
        for (text_id, source_path) in rows_true:
            comprehension = self.db.get_text_comprehension(text_id)  # e.g. fetch from DB
            if comprehension is None:
                comp_str = "N/A"
            else:
                comp_str = f"{comprehension:.1f}%"

            display_text = f"[ID={text_id}] {os.path.basename(source_path)}  (Comp: {comp_str})"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, text_id)
            self.list_suggested_material.addItem(item)

        self.statusBar().showMessage("Study materials reloaded with filter: " + chosen_filter)

    def closeEvent(self, event):
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)



    from anki_connector import AnkiConnector
    anki_conn = AnkiConnector(host="127.0.0.1", port=8765)

    from database_manager import DatabaseManager
    db_manager = DatabaseManager("study_manager.db", anki=anki_conn)

    window = CentralHub(db_manager, anki_conn)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()