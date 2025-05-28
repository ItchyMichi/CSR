import logging
import os
from typing import Optional

from content_parser import ContentParser
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QScrollArea, QGridLayout, QTreeWidget, QTreeWidgetItem,
    QCheckBox, QWidget, QSizePolicy, QToolBar, QAction, QMessageBox,
    QStackedWidget, QLineEdit, QPushButton, QFormLayout, QGroupBox,
    QHBoxLayout, QPlainTextEdit, QSpacerItem, QComboBox, QToolButton, QWidgetAction, QButtonGroup, QRadioButton,
    QInputDialog, QMenu

)

logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QHBoxLayout, QMessageBox
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal


class ClickableWordLabel(QLabel):
    """Small QLabel subclass that emits a signal when clicked."""
    clicked = pyqtSignal(str, int)

    def __init__(self, text: str, dict_form_id: int, parent=None):
        super().__init__(text, parent)
        self.word_text = text
        self.dict_form_id = dict_form_id

    def mousePressEvent(self, event):
        self.clicked.emit(self.word_text, self.dict_form_id)
        super().mousePressEvent(event)


class SplitSubtitleDialog(QDialog):
    """
    Dialog for splitting a single subtitle, using mpv for playback.
    - start_sec, end_sec: the original times of the subtitle
    - subtitle_text: the full text to be split
    - mpv_player: an mpv.MPV instance
    """
    def __init__(self, start_sec, end_sec, subtitle_text, mpv_player, parent=None):
        super().__init__(parent)
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.subtitle_text = subtitle_text
        self.mpv_player = mpv_player

        self.new_subtitles = []  # Will become [(s1, e1, t1), (s2, e2, t2)]

        self.setWindowTitle("Split Subtitle (MPV version)")
        self.resize(600, 400)

        # Immediately jump mpv to the subtitle’s start
        if self.mpv_player:
            self.mpv_player.seek(self.start_sec, reference="absolute", precision="exact")
            # Optional: start paused or playing.
            # mpv uses "pause=False" to play, "pause=True" to pause.
            self.mpv_player.pause = False  # start playing?

        self.init_ui()
        self.init_timer()

    def init_ui(self):
        layout = QVBoxLayout(self)

        lbl_instructions = QLabel(
            "Highlight the portion of text that belongs to the first subtitle.\n"
            "When you click 'Split at this Position', we'll use the current mpv time.\n"
            "If mpv goes beyond the end, it'll rewind to the start automatically."
        )
        lbl_instructions.setWordWrap(True)
        layout.addWidget(lbl_instructions)

        self.text_edit = QPlainTextEdit(self.subtitle_text)
        layout.addWidget(self.text_edit, stretch=1)

        # Show highlighted portion
        self.highlighted_text_box = QPlainTextEdit()
        self.highlighted_text_box.setReadOnly(True)
        self.highlighted_text_box.setFixedHeight(60)
        layout.addWidget(self.highlighted_text_box)

        # Connect selectionChanged
        self.text_edit.selectionChanged.connect(self.on_selection_changed)

        # Bottom row of buttons
        btn_layout = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        self.btn_rewind = QPushButton("Rewind")
        self.btn_split = QPushButton("Split at this Position")

        btn_layout.addWidget(self.btn_play)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_rewind)
        btn_layout.addWidget(self.btn_split)

        layout.addLayout(btn_layout)

        # Connect signals
        self.btn_play.clicked.connect(self.on_play_clicked)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_rewind.clicked.connect(self.on_rewind_clicked)
        self.btn_split.clicked.connect(self.on_split_clicked)

        # A "Cancel" or "Close" button
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        layout.addWidget(self.btn_close)

    def init_timer(self):
        """Start a QTimer that checks if mpv time_pos has passed end_sec."""
        self.timer = QTimer(self)
        self.timer.setInterval(200)  # check 5 times a second
        self.timer.timeout.connect(self.check_playback_position)
        self.timer.start()

    def check_playback_position(self):
        if not self.mpv_player:
            return
        pos = self.mpv_player.time_pos  # could be None if not playing yet
        if pos is None:
            return
        if pos > self.end_sec:
            # Rewind
            self.mpv_player.seek(self.start_sec, reference="absolute", precision="exact")

    def on_selection_changed(self):
        cursor = self.text_edit.textCursor()
        selected_text = cursor.selectedText().replace('\u2029', '\n')
        self.highlighted_text_box.setPlainText(selected_text)

    def on_play_clicked(self):
        if self.mpv_player:
            self.mpv_player.pause = False  # unpause => play

    def on_pause_clicked(self):
        if self.mpv_player:
            self.mpv_player.pause = True  # pause => True

    def on_rewind_clicked(self):
        if self.mpv_player:
            self.mpv_player.seek(self.start_sec, reference="absolute", precision="exact")

    def on_split_clicked(self):
        """
        - Read current playback time from mpv => that’s the boundary
        - Gather highlight’s text range => the first subtitle text
        - Remaining text => second subtitle text
        - Build self.new_subtitles = [(s1,e1,text1), (s2,e2,text2)]
        - self.accept()
        """
        if not self.mpv_player:
            QMessageBox.warning(self, "No Player", "MPV player not available.")
            return

        current_time = self.mpv_player.time_pos or self.start_sec
        # Basic clamp
        if current_time < self.start_sec:
            current_time = self.start_sec
        elif current_time > self.end_sec:
            current_time = self.end_sec

        logger.info("Splitting at %.2f seconds", current_time)

        # Figure out text splitting from highlight
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            sel_start = cursor.selectionStart()
            sel_end = cursor.selectionEnd()
        else:
            # If nothing selected, put everything in the first, or handle differently
            sel_start = 0
            sel_end = len(self.subtitle_text)

        logger.info("Selection: %d - %d", sel_start, sel_end)

        text_for_first = self.subtitle_text[:sel_end]
        text_for_second = self.subtitle_text[sel_end:]

        logger.info("First: %s", text_for_first)

        # Build new lines
        sub1 = (self.start_sec, current_time, text_for_first)
        sub2 = (current_time, self.end_sec, text_for_second)
        self.new_subtitles = [sub1, sub2]

        logger.info("New subtitles: %s", self.new_subtitles)

        self.accept()

    def closeEvent(self, event):
        # Stop the timer to avoid references to mpv after dialog closes
        self.timer.stop()
        super().closeEvent(event)


class SubtitleWindow(QDialog):
    subtitleDoubleClicked = pyqtSignal(float)
    openVideoAtTime = pyqtSignal(int, float)
    open_video_tab = pyqtSignal(str, int)   # (mpv_uri, media_id)
    pausePlayRequested = pyqtSignal()
    editorBackToSubtitles = pyqtSignal()
    def __init__(self, subtitle_lines=None, parent=None, db_manager=None, anki_connector=None,
                 google_credentials=None, anki_media_path="", audio_player=None, openai_api_key=""):
        super().__init__(parent)
        self.db_manager = db_manager
        self.anki = anki_connector
        self.google_credentials = google_credentials
        self.anki_media_path = anki_media_path
        self.audio_player = audio_player
        self.openai_api_key = openai_api_key
        self.parser = ContentParser()
        self._subtitle_lines = []

        # Keep references to certain UI items so we can update them
        self.subtitle_editor_rows = []  # will hold row widgets for editor

        self.selected_dict_form_ids = set()
        self.anki_selected_dict_form_surfaces = {}
        self.current_font_size = 10  # Default font size
        self.selected_word_id = None
        self.selected_word_text = ""
        self.selected_word_label = None

        self.setWindowFlags(
            Qt.Window |
            Qt.WindowSystemMenuHint |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowCloseButtonHint
        )

        self.setWindowTitle("Subtitles + Word Selection + Episode Tree")
        self.resize(1000, 800)

        # 1) Create the main content widget + layout
        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget)

        # 2) Build the toolbar
        self.toolbar = QToolBar("Tools", self)
        main_layout.addWidget(self.toolbar)

        # 3) Add your existing actions
        self.action_font_increase = QAction("Font +", self)
        self.action_font_increase.triggered.connect(self.increase_font_size)

        self.action_font_decrease = QAction("Font -", self)
        self.action_font_decrease.triggered.connect(self.decrease_font_size)

        self.action_create_anki = QAction("Create Anki Card", self)
        self.action_create_anki.triggered.connect(self.on_create_anki_clicked)

        self.action_create_migaku = QAction("Create Anki Card (Migaku)", self)
        self.action_create_migaku.triggered.connect(self.create_anki_card_migaku)

        self.action_subtitle_editor = QAction("Subtitle Editor", self)
        self.action_subtitle_editor.triggered.connect(self.open_subtitle_editor)

        self.editor_button_group = None  # We'll create it in refresh_subtitle_editor

        # Add them to toolbar
        self.toolbar.addAction(self.action_font_increase)
        self.toolbar.addAction(self.action_font_decrease)
        self.toolbar.addAction(self.action_create_anki)
        self.toolbar.addAction(self.action_create_migaku)
        self.toolbar.addAction(self.action_subtitle_editor)

        # 4) Create the stacked widget
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget, stretch=1)

        # Page 0: Subtitles Page
        self.page_subtitles = QWidget()
        self.build_subtitles_page(self.page_subtitles)
        self.stacked_widget.addWidget(self.page_subtitles)

        # Page 1: Anki Editor Page
        self.page_anki_editor = QWidget()
        self.build_anki_editor_page(self.page_anki_editor)
        self.stacked_widget.addWidget(self.page_anki_editor)

        # Page 2: Dictionary Search Page
        self.page_dictionary = QWidget()
        self.build_dictionary_search_page(self.page_dictionary)
        self.stacked_widget.addWidget(self.page_dictionary)

        # Page 3: Subtitle Editor Page
        self.page_subtitle_editor = QWidget()
        self.build_subtitle_editor_page(self.page_subtitle_editor)
        self.stacked_widget.addWidget(self.page_subtitle_editor)

        # Page 4: Word Viewer Page
        self.page_word_viewer = QWidget()
        self.build_word_viewer_page(self.page_word_viewer)
        self.stacked_widget.addWidget(self.page_word_viewer)



        # 5) Wrap content_widget in a QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(content_widget)

        dialog_layout = QVBoxLayout(self)
        dialog_layout.addWidget(scroll_area)
        self.setLayout(dialog_layout)

        self._last_active_index = -1

        # Optionally load initial subtitles
        if subtitle_lines:
            self.set_subtitles(subtitle_lines)

        self.update_fonts()

    # ---------------------------------------------------------------------
    # Build the Subtitles Page (page 0)
    # ---------------------------------------------------------------------
    def build_subtitles_page(self, parent_widget: QWidget):
        layout = QVBoxLayout(parent_widget)

        label_sub = QLabel("Subtitles")
        layout.addWidget(label_sub)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)

        label_words = QLabel("Words in Selected Subtitle")
        layout.addWidget(label_words)

        self.words_scroll = QScrollArea()
        self.words_scroll.setWidgetResizable(True)

        self.words_container = QWidget()
        self.grid_layout = QGridLayout(self.words_container)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setHorizontalSpacing(5)
        self.grid_layout.setVerticalSpacing(3)
        self.grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.words_container.setLayout(self.grid_layout)
        self.words_scroll.setWidget(self.words_container)
        layout.addWidget(self.words_scroll)

        episodes_label = QLabel("Episodes containing all selected words")
        layout.addWidget(episodes_label)

        self.episode_tree = QTreeWidget()
        self.episode_tree.setColumnCount(1)
        self.episode_tree.setHeaderHidden(True)
        self.episode_tree.itemDoubleClicked.connect(self.on_episode_tree_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.on_subtitle_right_click)
        layout.addWidget(self.episode_tree)

    def on_subtitle_right_click(self, pos):
        """
        Called when the user right-clicks somewhere in the list_widget.
        We figure out which subtitle was clicked, then show a context menu
        with an option to Pause/Play the active video.
        """
        # 1) Convert the click position (pos) to a model index:
        item_index = self.list_widget.indexAt(pos)
        if not item_index.isValid():
            return  # user right-clicked on empty area

        row = item_index.row()
        if row < 0 or row >= len(self._subtitle_lines):
            return

        # (Optionally) store the clicked row if you need it:
        # self._right_clicked_row = row

        # 2) Build the menu
        menu = QMenu(self)
        action_pause_play = QAction("Pause/Play Video", self)
        action_pause_play.triggered.connect(self.emit_pause_play_signal)
        menu.addAction(action_pause_play)

        # 3) Show the menu at the cursor position (translated to global coords)
        menu.exec_(self.list_widget.mapToGlobal(pos))

    def emit_pause_play_signal(self):
        self.pausePlayRequested.emit()

    def increase_font_size(self):
        self.current_font_size += 1
        self.update_fonts()

    def decrease_font_size(self):
        if self.current_font_size > 1:
            self.current_font_size -= 1
            self.update_fonts()

    def create_anki_card_migaku(self):
        QMessageBox.information(self, "Create Migaku Card", "Migaku card creation triggered.")

        # ---------------------------------------------------------------------
        # Build the new Subtitle Editor Page (page 3)
        # ---------------------------------------------------------------------
    def build_subtitle_editor_page(self, parent_widget: QWidget):
        """
        Build a page that shows each subtitle in a row:
          [Start -] [StartTime hh:mm:ss] [Subtitle Text] [EndTime hh:mm:ss] [End +]
        With +/- for start/end time adjustments.
        """
        layout = QVBoxLayout(parent_widget)
        label = QLabel("Subtitle Editor")
        font = label.font()
        font.setBold(True)
        font.setPointSize(12)
        label.setFont(font)
        layout.addWidget(label)

        # A scroll area so we can list many subtitles in a column
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        # Container that holds all subtitle rows
        self.editor_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_container)
        self.editor_layout.setContentsMargins(5, 5, 5, 5)
        self.editor_layout.setSpacing(3)

        # We'll fill this container dynamically in refresh_subtitle_editor()
        scroll.setWidget(self.editor_container)
        layout.addWidget(scroll)

        # Add a "Back to Subtitles" button in the bottom (or you could do a toolbar action)
        btn_back = QPushButton("Back to Subtitles")
        btn_back.clicked.connect(self.on_back_to_subtitles_in_editor)
        layout.addWidget(btn_back)

        parent_widget.setLayout(layout)

    def on_back_to_subtitles_in_editor(self):
        """
        When user clicks 'Back to Subtitles' in the editor toolbar.
        """
        # 1) Remove the editor actions
        for act in self._editor_actions:
            self.toolbar.removeAction(act)
        self._editor_actions.clear()

        # 2) Re-add the old actions
        for old_act in self._old_actions:
            self.toolbar.addAction(old_act)

        # 3) STOP the editor loop timer
        if hasattr(self, '_editor_loop_timer') and self._editor_loop_timer:
            self._editor_loop_timer.stop()
            self._editor_loop_timer.deleteLater()
            self._editor_loop_timer = None

        # 4) Clear fields and switch to the Subtitles page
        logger.info("Returning to Subtitles page")
        self.clear_anki_editor_fields()
        self.stacked_widget.setCurrentWidget(self.page_subtitles)

        # 5) Emit the signal so the parent can update
        logger.info("Emitting editorBackToSubtitles")
        self.editorBackToSubtitles.emit()

    # ---------------------------------------------------------------------
    # Overwrite the placeholder open_subtitle_editor method
    # ---------------------------------------------------------------------
    def open_subtitle_editor(self):
        """
        Switch to the 'Subtitle Editor' page in the stacked widget.
        Rebuild the editor page UI, then replace the toolbar actions
        with Subtitle Editor actions:
        Back, Save, Split, Insert Before, Insert After, Delete.
        """
        # 1) Store the old toolbar actions
        self._old_actions = self.toolbar.actions()

        # 2) Remove them
        for act in self._old_actions:
            self.toolbar.removeAction(act)

        # 3) Create new subtitle-editor-specific actions
        self.action_back_to_subs_editor = QAction("Back to Subtitles", self)
        self.action_back_to_subs_editor.triggered.connect(self.on_back_to_subtitles_in_editor)
        self.toolbar.addAction(self.action_back_to_subs_editor)

        self.action_save_changes = QAction("Save Changes", self)
        self.action_save_changes.triggered.connect(self.on_save_changes_clicked)
        self.toolbar.addAction(self.action_save_changes)

        self.action_split_subtitle = QAction("Split Subtitle", self)
        self.action_split_subtitle.triggered.connect(self.on_split_subtitle_clicked)
        self.toolbar.addAction(self.action_split_subtitle)

        self.action_insert_before = QAction("Insert Before", self)
        self.action_insert_before.triggered.connect(self.on_insert_before_clicked)
        self.toolbar.addAction(self.action_insert_before)

        self.action_insert_after = QAction("Insert After", self)
        self.action_insert_after.triggered.connect(self.on_insert_after_clicked)
        self.toolbar.addAction(self.action_insert_after)

        self.action_delete_subtitle = QAction("Delete", self)
        self.action_delete_subtitle.triggered.connect(self.on_delete_subtitle_clicked)
        self.toolbar.addAction(self.action_delete_subtitle)



        # Keep them for restoring later
        self._editor_actions = [
            self.action_back_to_subs_editor,
            self.action_save_changes,
            self.action_split_subtitle,
            self.action_insert_before,
            self.action_insert_after,
            self.action_delete_subtitle
        ]

        # 4) Rebuild the rows in the editor page + switch pages
        self.refresh_subtitle_editor()
        self.stacked_widget.setCurrentWidget(self.page_subtitle_editor)

    def refresh_subtitle_editor(self):
        # Remove old rows
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.editor_button_group = QButtonGroup(self)
        self.editor_button_group.setExclusive(True)

        # 1) Connect a signal so we know when the user selects a subtitle
        self.editor_button_group.buttonClicked[int].connect(self.on_subtitle_radio_clicked)

        self.subtitle_editor_rows.clear()

        for idx, (start_sec, end_sec, text) in enumerate(self._subtitle_lines):
            row_widget = self.build_subtitle_editor_row(idx, start_sec, end_sec, text)
            self.editor_layout.addWidget(row_widget)
            self.subtitle_editor_rows.append(row_widget)

        self.editor_layout.addStretch(1)

    def on_refresh_subtitles_clicked(self):
        """
        Manually recollect the subtitle lines from the SubtitleWindow,
        then rebuild this editor’s list.
        """
        if not self.subtitle_window:
            print("No subtitle_window reference is set. Cannot refresh.")
            return

        new_lines = self.subtitle_window.get_current_subtitles()  # This must exist
        if not new_lines:
            new_lines = []  # fallback

        self._subtitle_lines = new_lines
        self.refresh_subtitle_editor()
        print("Subtitle Editor: manual refresh from SubtitleWindow complete.")

    def build_subtitle_editor_row(self, index, start_sec, end_sec, subtitle_text):
        row_container = QWidget()
        h_layout = QHBoxLayout(row_container)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(5)

        # Radio button
        radio = QRadioButton()
        self.editor_button_group.addButton(radio, index)
        h_layout.addWidget(radio)

        # START: minus
        btn_start_minus = QPushButton("-")
        btn_start_minus.setFixedWidth(25)
        btn_start_minus.clicked.connect(
            lambda: self.on_adjust_and_select(index, is_start=True, delta=-1)
        )
        h_layout.addWidget(btn_start_minus)

        # START time display
        start_edit = QLineEdit(self.seconds_to_hhmmss(start_sec))
        start_edit.setReadOnly(True)
        start_edit.setFixedWidth(80)
        h_layout.addWidget(start_edit)

        # START: plus
        btn_start_plus = QPushButton("+")
        btn_start_plus.setFixedWidth(25)
        btn_start_plus.clicked.connect(
            lambda: self.on_adjust_and_select(index, is_start=True, delta=1)
        )
        h_layout.addWidget(btn_start_plus)

        # TEXT
        text_edit = QLineEdit(subtitle_text)
        text_edit.textChanged.connect(
            lambda new_text, i=index: self.on_subtitle_text_changed(i, new_text)
        )
        h_layout.addWidget(text_edit, stretch=1)

        # END: minus
        btn_end_minus = QPushButton("-")
        btn_end_minus.setFixedWidth(25)
        btn_end_minus.clicked.connect(
            lambda: self.on_adjust_and_select(index, is_start=False, delta=-1)
        )
        h_layout.addWidget(btn_end_minus)

        # END time display
        end_edit = QLineEdit(self.seconds_to_hhmmss(end_sec))
        end_edit.setReadOnly(True)
        end_edit.setFixedWidth(80)
        h_layout.addWidget(end_edit)

        # END: plus
        btn_end_plus = QPushButton("+")
        btn_end_plus.setFixedWidth(25)
        btn_end_plus.clicked.connect(
            lambda: self.on_adjust_and_select(index, is_start=False, delta=1)
        )
        h_layout.addWidget(btn_end_plus)

        row_container.setLayout(h_layout)

        # Store references
        row_container._radio = radio
        row_container._start_edit = start_edit
        row_container._end_edit = end_edit

        return row_container

    def on_adjust_and_select(self, index, is_start, delta):
        # If you want to 're-toggle' the radio so it fires signals again:
        row_widget = self.subtitle_editor_rows[index]
        if row_widget._radio.isChecked():
            # Temporarily disable exclusivity, uncheck, and re-check
            self.editor_button_group.setExclusive(False)
            row_widget._radio.setChecked(False)
            self.editor_button_group.setExclusive(True)
        row_widget._radio.setChecked(True)

        # Perform the timing adjustment
        self.adjust_subtitle_time(index, is_start, delta)

        # Now update our loop range so the timer sees the *new* times.
        start_sec, end_sec, _ = self._subtitle_lines[index]
        self._current_subtitle_start = start_sec
        self._current_subtitle_end = end_sec

    def on_subtitle_text_changed(self, index, new_text):
        """
        If you allow direct text editing in the editor, store changes back to _subtitle_lines.
        """
        # _subtitle_lines[index] is (start, end, text)
        start_sec, end_sec, _ = self._subtitle_lines[index]
        self._subtitle_lines[index] = (start_sec, end_sec, new_text)

    def on_subtitle_radio_clicked(self, button_id: int):
        """
        Called automatically when the user clicks a radio button in the editor.
        We want to start playing that subtitle’s segment in mpv by default.
        """
        if button_id < 0 or button_id >= len(self._subtitle_lines):
            return

        start_sec, end_sec, _ = self._subtitle_lines[button_id]

        # Grab mpv from the parent window
        main_window = self.parent()
        if hasattr(main_window, "get_active_mpv_player"):
            mpv_player = main_window.get_active_mpv_player()
            if not mpv_player:
                QMessageBox.warning(self, "No Video", "No mpv player is active.")
                return
        else:
            QMessageBox.warning(
                self, "Missing Method",
                "Parent window does not implement get_active_mpv_player()."
            )
            return

        # Seek to start and play
        mpv_player.seek(start_sec, reference="absolute", precision="exact")
        mpv_player.pause = False  # unpause => start playing

        # Optional: store the current sub's range so we can loop it in a timer
        self._current_subtitle_start = start_sec
        self._current_subtitle_end = end_sec

        # If you haven't already, start (or restart) a timer in the editor
        # that checks if we went past _current_subtitle_end, and if so, rewind.
        # For example:
        self.start_editor_timer_for_looping()

    def start_editor_timer_for_looping(self):
        # If already have a timer, stop+delete it so we don’t have duplicates
        if hasattr(self, "_editor_loop_timer") and self._editor_loop_timer:
            self._editor_loop_timer.stop()
            self._editor_loop_timer.deleteLater()

        self._editor_loop_timer = QTimer(self)
        self._editor_loop_timer.setInterval(200)  # 5x per second
        self._editor_loop_timer.timeout.connect(self.on_editor_timer_tick)
        self._editor_loop_timer.start()

    def on_editor_timer_tick(self):
        main_window = self.parent()
        if not hasattr(main_window, "get_active_mpv_player"):
            return
        mpv_player = main_window.get_active_mpv_player()
        if not mpv_player:
            return

        pos = mpv_player.time_pos
        if pos is None:
            return

        # If the user has changed which radio is selected, we store the new range
        # in self._current_subtitle_end, etc. So if pos > that end, go back:
        if self._current_subtitle_end and pos > self._current_subtitle_end:
            mpv_player.seek(self._current_subtitle_start, reference="absolute", precision="exact")

    def on_save_changes_clicked(self):
        """
        Example of a more robust approach:
          1) (Optional) do fix_all_overlaps() so user’s final timeline has zero collisions.
          2) Then commit _subtitle_lines to the DB as usual.
        """
        if not self._subtitle_lines:
            QMessageBox.warning(self, "No Subtitles", "No subtitles to save.")
            return

        # 1) Enforce no overlaps
        self.fix_all_overlaps(min_gap=0.05)  # or 0.1s, etc.
        # 2) (Optional) enforce min durations
        self.fix_minimum_duration(min_dur=0.4)
        # 3) fix_all_overlaps again
        self.fix_all_overlaps(min_gap=0.05)

        # 4) Then proceed with your normal "save to DB" steps
        text_id = self.get_current_text_id_for_editor()
        if not text_id:
            QMessageBox.warning(self, "Missing text_id",
                                "Could not find a matching text_id (no unchanged lines). "
                                "Please store text_id or provide one manually.")
            return

        try:
            with self.db_manager._conn:
                # 1) Retrieve the old sentence IDs for this text
                old_sentences = self.get_sentences_for_text_id(text_id)
                # each = (sentence_id, content, start_time, end_time)

                # 2) For each old sentence, decrement frequencies
                for (sentence_id, old_content, old_start, old_end) in old_sentences:
                    sf_rows = self.db_manager.get_surface_forms_for_sentence(sentence_id)
                    # each sf_row might be (surface_form_id, surface_form, dict_form_id, base_form, known)
                    for (surface_form_id, surface_form, df_id, base_form, known) in sf_rows:
                        self.decrement_surface_form_frequency(surface_form_id)
                        freq = self.get_surface_form_frequency(surface_form_id)
                        if freq <= 0:
                            self.remove_surface_form_completely(surface_form_id)

                    self.db_manager.remove_surface_form_sentence_links(sentence_id)

                # 3) Remove the old sentences themselves
                self.db_manager.remove_sentences_for_text(text_id)

                # 4) Insert the new lines + parse
                for (start_sec, end_sec, new_text) in self._subtitle_lines:
                    sentence_id = self.db_manager.insert_sentence(text_id, new_text, start_sec, end_sec)

                    tokens = self.parser.parse_content(new_text)
                    for tk in tokens:
                        dict_form_id = self.db_manager.get_or_create_dictionary_form(
                            base_form=tk["base_form"],
                            reading=tk["reading"],
                            pos=tk["pos"]
                        )
                        sf_id = self.db_manager.add_surface_form(
                            dict_form_id=dict_form_id,
                            surface_form=tk["surface_form"],
                            reading=tk["reading"],
                            pos=tk["pos"],
                            sentence_id=sentence_id,
                            card_id=None
                        )
                        # add_surface_form increments frequency by +1

                    self.update_unknown_count_for_sentence(sentence_id)

            QMessageBox.information(self, "Save Complete", "Subtitles updated in the database.")

        except Exception as e:
            logger.exception("Error saving subtitles: %s", e)
            QMessageBox.critical(self, "Save Failed", f"An error occurred:\n{e}")

    def get_sentences_for_text_id(self, text_id: int):
        """
        Return a list of tuples: (sentence_id, content, start_time, end_time)
        for all sentences associated with the given text_id.
        """
        cur = self.db_manager._conn.cursor()
        cur.execute("""
            SELECT sentence_id, content, start_time, end_time
            FROM sentences
            WHERE text_id = ?
            ORDER BY start_time
        """, (text_id,))
        rows = cur.fetchall()
        return rows

    def find_untouched_subtitle_line(self):
        """
        Look for a line in the current (edited) _subtitle_lines that also appears
        in the original _original_subtitle_lines. Return that tuple or None.
        """
        original_set = set(self._original_subtitle_lines)
        for line in self._subtitle_lines:
            if line in original_set:
                return line
        return None

    def get_current_text_id_for_editor(self) -> Optional[int]:
        """
        Use find_untouched_subtitle_line() to pick a line that hasn't changed,
        and query the DB's 'sentences' table to find text_id by matching
        (content, start_time, end_time) within a small float tolerance.
        """
        unchanged_line = self.find_untouched_subtitle_line()
        if unchanged_line is None:
            return None

        (start_sec, end_sec, content) = unchanged_line

        cur = self.db_manager._conn.cursor()
        cur.execute("""
            SELECT text_id
              FROM sentences
             WHERE content = ?
               AND ABS(start_time - ?) < 0.001
               AND ABS(end_time - ?) < 0.001
             LIMIT 1
        """, (content, start_sec, end_sec))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def decrement_surface_form_frequency(self, surface_form_id: int):
        cur = self.db_manager._conn.cursor()
        cur.execute("""
            UPDATE surface_forms
               SET frequency = frequency - 1
             WHERE surface_form_id = ?
        """, (surface_form_id,))
        self.db_manager._conn.commit()

    def get_surface_form_frequency(self, surface_form_id: int) -> int:
        cur = self.db_manager._conn.cursor()
        cur.execute("""
            SELECT frequency FROM surface_forms WHERE surface_form_id = ?
        """, (surface_form_id,))
        row = cur.fetchone()
        return row[0] if row else 0

    def remove_surface_form_completely(self, surface_form_id: int):
        cur = self.db_manager._conn.cursor()
        cur.execute("DELETE FROM surface_forms WHERE surface_form_id = ?", (surface_form_id,))
        self.db_manager._conn.commit()

    def on_split_subtitle_clicked(self):
        selected_index = self.editor_button_group.checkedId()
        if selected_index < 0:
            QMessageBox.warning(self, "Split Subtitle", "No subtitle selected.")
            return

        start_sec, end_sec, full_text = self._subtitle_lines[selected_index]

        # 1) Grab mpv from the parent (which is usually your main window)
        main_window = self.parent()
        if hasattr(main_window, "get_active_mpv_player"):
            mpv_player = main_window.get_active_mpv_player()
            if not mpv_player:
                QMessageBox.warning(self, "No Video", "No mpv player is active.")
                return
        else:
            QMessageBox.warning(self, "Missing Method",
                                "Parent window does not implement get_active_mpv_player().")
            return



        # 2) Now create the dialog, passing in the real mpv player
        dialog = SplitSubtitleDialog(
            start_sec=start_sec,
            end_sec=end_sec,
            subtitle_text=full_text,
            mpv_player=mpv_player,  # <-- Correct argument name
            parent=self
        )
        result = dialog.exec_()

        if result == QDialog.Accepted:
            new_subs = dialog.new_subtitles
            if not new_subs or len(new_subs) != 2:
                QMessageBox.warning(self, "Split Error", "Did not receive valid split subtitles.")
                return

            # Remove the old one...
            del self._subtitle_lines[selected_index]
            # ...Insert the two new lines in its place
            # (You might want to keep the same index for the first, then insert the second right after)
            self._subtitle_lines.insert(selected_index, new_subs[1])
            self._subtitle_lines.insert(selected_index, new_subs[0])

            # Rebuild the editor
            self.refresh_subtitle_editor()
            QMessageBox.information(self, "Split Subtitle", "Subtitle split in memory. Remember to Save Changes!")

    def on_insert_before_clicked(self):
        """
        Insert a new subtitle entry before the currently selected subtitle.
        By default, we'll create a 1-second long placeholder, ending just before the current subtitle's start.
        """
        selected_index = self.editor_button_group.checkedId()
        if selected_index < 0:
            QMessageBox.warning(self, "Insert Before", "No subtitle selected.")
            return

        # Get the selected subtitle’s start/end
        curr_start, curr_end, curr_text = self._subtitle_lines[selected_index]

        # Define a new subtitle that ends right before the current one (e.g. 0.05s gap).
        # We'll pick a 1-second duration by default, or clamp it if it goes below 0.
        gap = 0.05
        new_end = max(curr_start - gap, 0)  # can't go negative
        new_start = max(new_end - 1.0, 0)  # 1-second length
        # Ensure we don't accidentally invert them if there's no room.
        if new_start >= new_end:
            # If there's not even 0.05s before the current sub, place this new one at t=0..1
            new_start = 0
            new_end = 1.0

        new_subtitle = (new_start, new_end, "New subtitle")

        # Insert it into the list
        self._subtitle_lines.insert(selected_index, new_subtitle)

        # Optionally fix collisions and durations
        self.fix_all_overlaps(min_gap=0.05)
        self.fix_minimum_duration(min_dur=0.4)
        self.fix_all_overlaps(min_gap=0.05)

        # Rebuild the editor
        self.refresh_subtitle_editor()

        QMessageBox.information(self, "Insert Before",
                                "Inserted a new subtitle before the selected one.\n"
                                "Please adjust times/text as needed, then Save Changes.")

    def on_insert_after_clicked(self):
        """
        Insert a new subtitle entry after the currently selected subtitle.
        We'll create a placeholder that starts just after the current subtitle ends.
        """
        selected_index = self.editor_button_group.checkedId()
        if selected_index < 0:
            QMessageBox.warning(self, "Insert After", "No subtitle selected.")
            return

        # Get the selected subtitle’s start/end
        curr_start, curr_end, curr_text = self._subtitle_lines[selected_index]

        # Define a new subtitle that starts right after the current one, 0.05s gap
        gap = 0.05
        new_start = curr_end + gap
        new_end = new_start + 1.0  # 1-second duration by default
        new_subtitle = (new_start, new_end, "New subtitle")

        # Insert it at index+1
        insert_pos = selected_index + 1
        self._subtitle_lines.insert(insert_pos, new_subtitle)

        # Optionally fix collisions and durations
        self.fix_all_overlaps(min_gap=0.05)
        self.fix_minimum_duration(min_dur=0.4)
        self.fix_all_overlaps(min_gap=0.05)

        # Rebuild the editor
        self.refresh_subtitle_editor()

        QMessageBox.information(self, "Insert After",
                                "Inserted a new subtitle after the selected one.\n"
                                "Please adjust times/text as needed, then Save Changes.")

    def on_delete_subtitle_clicked(self):
        """
        Delete the currently selected subtitle from the in-memory list.
        """
        selected_index = self.editor_button_group.checkedId()
        if selected_index < 0:
            QMessageBox.warning(self, "Delete Subtitle", "No subtitle selected.")
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this subtitle?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        del self._subtitle_lines[selected_index]

        # Rebuild the editor
        self.refresh_subtitle_editor()

        QMessageBox.information(self, "Delete Subtitle",
                                "The selected subtitle has been removed.\n"
                                "Remember to Save Changes if you want to keep this deletion.")

    def adjust_subtitle_time(self, index, is_start, delta):
        start_sec, end_sec, text = self._subtitle_lines[index]

        if is_start:
            new_start = start_sec + delta
            if new_start < 0:
                new_start = 0
            if new_start >= end_sec:
                new_start = end_sec - 0.01
            start_sec = new_start
        else:
            new_end = end_sec + delta
            if new_end < 0:
                new_end = 0
            if new_end <= start_sec:
                new_end = start_sec + 0.01
            end_sec = new_end

        # Update the current subtitle in memory
        self._subtitle_lines[index] = (start_sec, end_sec, text)

        # *Optional* step: if you want to do any quick checks against
        # the next/previous sub BEFORE you fix collisions, do it here.

        # Fix collisions
        self.fix_collision_forward(index)
        self.fix_collision_backward(index)

        # *After* collisions are fixed, you can do a check to see if
        # there's still any overlap that couldn't be fixed automatically
        if self.check_any_remaining_overlap(index):
            # For example, show a message or forcibly change times:
            self.fix_all_overlaps(min_gap=0.05)

        # Refresh the row UI
        self._refresh_editor_row(index)
        if index > 0:
            self._refresh_editor_row(index - 1)
        if index < len(self._subtitle_lines) - 1:
            self._refresh_editor_row(index + 1)

    def check_any_remaining_overlap(self, index) -> bool:
        """
        Returns True if there's still any overlap between self._subtitle_lines[index]
        and its neighbors AFTER fix_collision_... attempts.
        """
        start_sec, end_sec, _ = self._subtitle_lines[index]

        # Check overlap with the previous subtitle
        if index > 0:
            prev_start, prev_end, _ = self._subtitle_lines[index - 1]
            if prev_end > start_sec:  # means overlap
                return True

        # Check overlap with the next subtitle
        if index < len(self._subtitle_lines) - 1:
            next_start, next_end, _ = self._subtitle_lines[index + 1]
            if next_start < end_sec:  # means overlap
                return True

        return False

    def fix_collision_forward(self, index, min_gap=0.01):
        """
        Instead of pushing the entire next subtitle forward, we just
        'shorten' the next subtitle by adjusting its start time so it
        no longer overlaps the current one.
        """
        # current sub's times
        startA, endA, textA = self._subtitle_lines[index]

        # If there's a next subtitle
        if index + 1 < len(self._subtitle_lines):
            startB, endB, textB = self._subtitle_lines[index + 1]

            # The earliest startB can be, without overlapping
            required_startB = endA + min_gap

            if startB < required_startB:
                # So the two subs overlap. We'll clamp sub B to start at required_startB.
                new_startB = required_startB

                # If new_startB >= endB, the next sub has no positive duration left,
                # so you can either delete it or clamp it to 0.01s, etc.
                if new_startB >= endB:
                    # Example: remove the sub if it's now zero-length
                    del self._subtitle_lines[index + 1]
                else:
                    # "Shorten" sub B by moving its start forward
                    self._subtitle_lines[index + 1] = (new_startB, endB, textB)

    def fix_collision_backward(self, index, min_gap=0.01):
        """
        If sub[index] intrudes into the *previous* subtitle,
        we 'shorten' the previous sub’s end time so no overlap remains.
        """
        startA, endA, textA = self._subtitle_lines[index]
        if index - 1 >= 0:
            startB, endB, textB = self._subtitle_lines[index - 1]
            required_endB = startA - min_gap
            if endB > required_endB:
                new_endB = required_endB
                if new_endB <= startB:
                    # That means sub B is zero-length or inverted => remove it
                    del self._subtitle_lines[index - 1]
                    # adjust 'index' because the list shrinks
                else:
                    # shorten the previous sub’s end
                    self._subtitle_lines[index - 1] = (startB, new_endB, textB)

    def fix_all_overlaps(self, min_gap=0.02):
        """
        Sort all subtitles by start time, then do a single pass left-to-right
        to ensure no overlaps. Subtitles that collide will be 'pushed forward'.
        """
        # 1) Sort in-place by start time
        self._subtitle_lines.sort(key=lambda sub: sub[0])

        # 2) Single pass to ensure each sub starts after the previous ends + min_gap
        for i in range(len(self._subtitle_lines) - 1):
            startA, endA, textA = self._subtitle_lines[i]
            startB, endB, textB = self._subtitle_lines[i + 1]

            # We want: startB >= endA + min_gap
            required_startB = endA + min_gap
            if startB < required_startB:
                # shift sub B forward
                shift = required_startB - startB
                startB += shift
                endB += shift
                self._subtitle_lines[i + 1] = (startB, endB, textB)

        # 3) Optionally do a second pass right-to-left if you want minimal “stretch”.
        #    Or just do as many passes as needed until stable. Something like:
        #
        # stable = False
        # while not stable:
        #     stable = True
        #     for i in range(len(self._subtitle_lines) - 1):
        #         ...
        #         if collision:
        #             stable = False
        #             fix collision

    def _refresh_editor_row(self, index):
        """Helper to update row UI from self._subtitle_lines[index]."""
        row_widget = self.subtitle_editor_rows[index]
        start_sec, end_sec, text = self._subtitle_lines[index]
        row_widget._start_edit.setText(self.seconds_to_hhmmss(start_sec))
        row_widget._end_edit.setText(self.seconds_to_hhmmss(end_sec))
        # If you also allow changing text, you can update that too if needed.

    def fix_minimum_duration(self, min_dur=0.4):
        for i, (start, end, text) in enumerate(self._subtitle_lines):
            dur = end - start
            if dur < min_dur:
                needed = min_dur - dur
                end += needed
                self._subtitle_lines[i] = (start, end, text)
        # Then possibly fix overlaps again,
        # because extending the end might now collide with the next sub.

    @staticmethod
    def seconds_to_hhmmss(total_seconds):
        """
        Convert float seconds to hh:mm:ss (integer) format.
        If you need more precise fractions, adapt accordingly.
        """
        hours = int(total_seconds // 3600)
        mins = int((total_seconds % 3600) // 60)
        secs = int(total_seconds % 60)
        return f"{hours:02d}:{mins:02d}:{secs:02d}"

    from PyQt5.QtGui import QFont

    def update_fonts(self):
        """
        Re-apply self.current_font_size to all major parent widgets so that
        any child controls automatically get the updated font size.
        """
        new_font = QFont()
        new_font.setPointSize(self.current_font_size)

        #
        # -- Subtitles Page --
        #
        self.list_widget.setFont(new_font)
        self.words_container.setFont(new_font)
        self.episode_tree.setFont(new_font)

        #
        # -- Subtitle Editor Page --
        #
        self.page_subtitle_editor.setFont(new_font)
        self.editor_container.setFont(new_font)
        # (If you have row widgets you recreate dynamically, this ensures
        #  their parent has the correct font, so they inherit it.)

        #
        # -- Anki Editor Page --
        #
        self.page_anki_editor.setFont(new_font)
        self.anki_word_container.setFont(new_font)  # parent of the grid

        # Individual fields and combos:
        self.deck_combo.setFont(new_font)
        self.field_native_word.setFont(new_font)
        self.field_native_sentence.setFont(new_font)
        self.field_translated_word.setFont(new_font)
        self.field_translated_sentence.setFont(new_font)
        self.field_word_audio.setFont(new_font)
        self.field_sentence_audio.setFont(new_font)
        self.field_image.setFont(new_font)
        self.field_pos.setFont(new_font)

        #
        # -- Dictionary Search Page --
        #
        self.page_dictionary.setFont(new_font)
        self.dict_search_input.setFont(new_font)
        self.dict_search_result.setFont(new_font)
        self.btn_do_search.setFont(new_font)
        self.btn_back_to_card.setFont(new_font)

        #
        # -- Toolbar (optional) --
        #
        self.toolbar.setFont(new_font)

    def set_subtitles(self, subtitle_lines):
        """
        Called when you first load or replace the subtitle lines in this window.
        We store them in both _subtitle_lines and _original_subtitle_lines so we can
        detect unchanged lines later.
        """
        logger.info("Setting %d subtitle lines", len(subtitle_lines))
        self._subtitle_lines = list(subtitle_lines)
        self._original_subtitle_lines = list(subtitle_lines)  # keep a copy for reference

        self.list_widget.clear()
        for (start, end, text) in subtitle_lines:
            start_str = self.seconds_to_hhmmss(start)
            end_str = self.seconds_to_hhmmss(end)
            display_str = f"{start_str} - {end_str}  {text}"
            self.list_widget.addItem(display_str)

        self.update_fonts()
        # Also refresh editor page if we want
        self.refresh_subtitle_editor()

    def on_item_double_clicked(self, item: QListWidgetItem):
        row = self.list_widget.row(item)
        if row < 0 or row >= len(self._subtitle_lines):
            return
        start_time, end_time, text = self._subtitle_lines[row]
        self.subtitleDoubleClicked.emit(start_time)
        self.display_words_for_subtitle(row)


    def clear_selected_words(self):
        self.selected_dict_form_ids.clear()
        self.build_episode_tree_for_selected_words()

    def display_words_for_subtitle(self, index: int):
        if index < 0 or index >= len(self._subtitle_lines):
            return
        start_time, end_time, text = self._subtitle_lines[index]
        self.clear_selected_words()
        self.clear_grid_layout()

        if not self.db_manager:
            return

        forms = self.db_manager.get_surface_forms_for_text_content(text)
        if not forms:
            no_label = QLabel("No words found for this subtitle.")
            self.grid_layout.addWidget(no_label, 0, 0, 1, 1)
            return

        # ——— HEADERS ———
        word_header = QLabel("Word")
        word_header.setAlignment(Qt.AlignCenter)
        self.grid_layout.addWidget(word_header, 0, 0)

        base_header = QLabel("Base Form")
        base_header.setAlignment(Qt.AlignCenter)
        self.grid_layout.addWidget(base_header, 1, 0)

        known_header = QLabel("Known?")
        known_header.setAlignment(Qt.AlignCenter)
        self.grid_layout.addWidget(known_header, 2, 0)

        select_header = QLabel("Select")
        select_header.setAlignment(Qt.AlignCenter)
        self.grid_layout.addWidget(select_header, 3, 0)

        # ——— PER-WORD COLUMNS ———
        for col, (sf_id, surface, df_id, base_form, known) in enumerate(forms, start=1):
            # 1) Word label
            word_label = QLabel(surface)
            word_label.setAlignment(Qt.AlignCenter)
            word_label.setAutoFillBackground(True)
            pal = word_label.palette()
            pal.setColor(QPalette.Window, QColor("#ccffcc") if known else QColor("#ffcccc"))
            word_label.setPalette(pal)
            self.grid_layout.addWidget(word_label, 0, col)

            # 2) Base-form label
            base_label = QLabel(f"({base_form})")
            base_label.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(base_label, 1, col)

            # 3) Known-status radio
            radio = QRadioButton("Known")
            radio.setChecked(bool(known))
            radio.setAutoExclusive(False)
            radio.toggled.connect(
                lambda checked, d_id=df_id: self.on_word_known_toggled(d_id, checked)
            )
            self.grid_layout.addWidget(radio, 2, col, alignment=Qt.AlignHCenter)

            # 4) Selection checkbox
            cb = QCheckBox()
            cb.setChecked(False)
            cb.stateChanged.connect(
                lambda state, d_id=df_id: self.on_select_checkbox_changed(d_id, state)
            )
            self.grid_layout.addWidget(cb, 3, col, alignment=Qt.AlignHCenter)

        # ——— FINISH LAYOUT ———
        total_cols = len(forms) + 1
        for c in range(total_cols):
            self.grid_layout.setColumnStretch(c, 0)

        # Let the word-row expand vertically if the widget grows
        self.grid_layout.setRowStretch(0, 1)

        # Refresh fonts (if you need consistent scaling)
        self.update_fonts()

    def on_word_known_toggled(self, dict_form_id: int, is_known: bool):
        """
        Called when the user toggles the radio button for a given dict_form_id.
        If 'is_known' is True, mark the form as known in the database.
        If 'is_known' is False, mark it unknown.
        """
        if not self.db_manager:
            return

        self.db_manager.set_dictionary_form_known(dict_form_id, is_known)
        self.db_manager.update_unknown_counts_for_dict_form(dict_form_id)

        # Optionally, re-draw the subtitle words to update colors
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.display_words_for_subtitle(current_row)

    def clear_grid_layout(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def on_select_checkbox_changed(self, dict_form_id, state):
        checked = (state == Qt.Checked)
        if checked:
            self.selected_dict_form_ids.add(dict_form_id)
        else:
            self.selected_dict_form_ids.discard(dict_form_id)
        self.build_episode_tree_for_selected_words()

    def build_episode_tree_for_selected_words(self):
        self.episode_tree.clear()
        if not self.selected_dict_form_ids:
            top_item = QTreeWidgetItem(["No words selected"])
            self.episode_tree.addTopLevelItem(top_item)
            return

        sentence_ids = self.db_manager.get_sentences_with_all_dict_forms(self.selected_dict_form_ids)
        if not sentence_ids:
            no_item = QTreeWidgetItem(["No subtitles contain all selected words"])
            self.episode_tree.addTopLevelItem(no_item)
            return

        media_map = {}
        for sid in sentence_ids:
            info = self.db_manager.get_sentence_media_info(sid)
            if not info:
                continue
            m_id, stime, ctext = info
            media_map.setdefault(m_id, []).append((sid, stime, ctext))

        for media_id, lines in media_map.items():
            ep_name = self.db_manager.get_media_display_name(media_id)
            ep_item = QTreeWidgetItem([ep_name])
            self.episode_tree.addTopLevelItem(ep_item)
            lines.sort(key=lambda x: x[1])
            for (sid, stime, ctext) in lines:
                hhmmss = self.seconds_to_hhmmss(stime)
                line_text = f"{hhmmss} => {ctext}"
                child_item = QTreeWidgetItem([line_text])
                child_item.setData(0, Qt.UserRole, ("subtitle_line", media_id, stime))
                ep_item.addChild(child_item)

        self.episode_tree.collapseAll()

    def on_episode_tree_double_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        (tag, media_id, stime) = data
        if tag in ("subtitle_line", "media_file"):
            # 1) Pause the current video (emit the signal that your main window or tab listens for)
            #self.pausePlayRequested.emit()

            info = self.db_manager.get_media_info(media_id)
            if not info:
                return
            mpv_uri = info["mpv_path"]

            # 2) Now emit the signal to open the new tab
            self.openVideoAtTime.emit(media_id, stime)

    def highlight_current_time(self, current_time: float):
        active_index = -1
        for i, (start, end, txt) in enumerate(self._subtitle_lines):
            if start <= current_time < end:
                active_index = i
                break
        if active_index >= 0:
            if active_index != self._last_active_index:
                self._last_active_index = active_index
                self.list_widget.setCurrentRow(active_index)
                item = self.list_widget.item(active_index)
                if item:
                    self.list_widget.scrollToItem(item)
                self.display_words_for_subtitle(active_index)
        else:
            self.clear_grid_layout()
            self._last_active_index = -1

    ########################################################################
    # (Continuation of SubtitleWindow)
    # Methods for the "Create Anki Card" page + translation fields
    ########################################################################
    def build_anki_editor_page(self, parent_widget: QWidget):
        outer_layout = QVBoxLayout(parent_widget)

        # -- Create a horizontal layout to hold the title label and deck combo --
        title_layout = QHBoxLayout()

        lbl_title = QLabel("Create Anki Card (Word Selection In Situ)")
        f = lbl_title.font()
        f.setBold(True)
        f.setPointSize(12)
        lbl_title.setFont(f)
        title_layout.addWidget(lbl_title)

        # The combo box for deck selection:
        self.deck_combo = QComboBox()
        title_layout.addWidget(QLabel("Deck:"))
        title_layout.addWidget(self.deck_combo)

        outer_layout.addLayout(title_layout)

        # --- WORD SELECTION AREA ---
        word_select_group = QGroupBox("Select Word(s) For 'Native Word'")
        vbox_select = QVBoxLayout(word_select_group)

        self.anki_scroll = QScrollArea()
        self.anki_scroll.setWidgetResizable(True)
        # Container + Grid
        self.anki_word_container = QWidget()
        self.anki_grid_layout = QGridLayout(self.anki_word_container)
        self.anki_grid_layout.setContentsMargins(5, 5, 5, 5)
        self.anki_grid_layout.setHorizontalSpacing(5)
        self.anki_grid_layout.setVerticalSpacing(3)
        self.anki_grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.anki_word_container.setLayout(self.anki_grid_layout)
        self.anki_scroll.setWidget(self.anki_word_container)

        vbox_select.addWidget(self.anki_scroll)
        outer_layout.addWidget(word_select_group)

        # --- CARD DETAILS AREA ---
        card_details_group = QGroupBox("Card Details")
        form_layout = QFormLayout(card_details_group)

        # 1) “Native Word”
        self.field_native_word = QLineEdit()
        form_layout.addRow("Native Word:", self.field_native_word)

        # 2) “Native Sentence”
        self.field_native_sentence = QPlainTextEdit()
        self.field_native_sentence.setFixedHeight(60)
        form_layout.addRow("Native Sentence:", self.field_native_sentence)

        # 3) Word Audio
        audio_layout_word = QHBoxLayout()
        self.field_word_audio = QLineEdit()
        audio_layout_word.addWidget(self.field_word_audio)
        btn_play_word = QPushButton("Play")
        btn_play_word.clicked.connect(self.play_word_audio_placeholder)
        audio_layout_word.addWidget(btn_play_word)
        btn_gen_word_audio = QPushButton("Generate Word Audio")
        btn_gen_word_audio.clicked.connect(self.generate_word_audio_placeholder)
        audio_layout_word.addWidget(btn_gen_word_audio)
        form_layout.addRow("Word Audio:", audio_layout_word)

        # 4) Sentence Audio
        audio_layout_sentence = QVBoxLayout()
        row1 = QHBoxLayout()
        self.field_sentence_audio = QLineEdit()
        row1.addWidget(self.field_sentence_audio)
        btn_play_sentence = QPushButton("Play")
        btn_play_sentence.clicked.connect(self.play_sentence_audio_all)
        row1.addWidget(btn_play_sentence)
        audio_layout_sentence.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Video Tab:"))
        self.combo_video_tabs_for_sentence = QComboBox()
        self.combo_video_tabs_for_sentence.addItem("Tab A (placeholder)")
        self.combo_video_tabs_for_sentence.addItem("Tab B (placeholder)")
        row2.addWidget(self.combo_video_tabs_for_sentence)
        btn_capture_sentence_audio = QPushButton("Capture Audio (placeholder)")
        btn_capture_sentence_audio.clicked.connect(self.capture_sentence_audio_placeholder)
        row2.addWidget(btn_capture_sentence_audio)
        audio_layout_sentence.addLayout(row2)

        form_layout.addRow("Sentence Audio:", audio_layout_sentence)

        # 5) POS
        self.field_pos = QPlainTextEdit()
        self.field_pos.setReadOnly(True)
        self.field_pos.setFixedHeight(60)
        form_layout.addRow("POS (all selected):", self.field_pos)

        # ------------------- NEW FIELD for IMAGES -------------------
        self.field_image = QLineEdit()
        form_layout.addRow("Images Field:", self.field_image)
        # We'll connect a signal so that when user edits the text, we re-preview images:
        self.field_image.textChanged.connect(self.on_field_image_changed)
        # -----------------------------------------------------------

        # 6) Images - now a scroll area that shows all <img src="..."> from field_image
        image_layout = QVBoxLayout()

        # Scroll area for image previews
        self.images_scroll = QScrollArea()
        self.images_scroll.setWidgetResizable(True)

        # Container for actual image labels
        self.images_container = QWidget()
        self.images_layout = QHBoxLayout(self.images_container)
        self.images_layout.setSpacing(5)
        self.images_layout.setContentsMargins(0, 0, 0, 0)
        self.images_container.setLayout(self.images_layout)

        self.images_scroll.setWidget(self.images_container)
        image_layout.addWidget(self.images_scroll)

        row_img = QHBoxLayout()
        row_img.addWidget(QLabel("Video Tab:"))
        self.combo_video_tabs_for_image = QComboBox()
        self.combo_video_tabs_for_image.addItem("Tab A (placeholder)")
        self.combo_video_tabs_for_image.addItem("Tab B (placeholder)")
        row_img.addWidget(self.combo_video_tabs_for_image)
        btn_capture_image = QPushButton("Capture Screenshot (placeholder)")
        btn_capture_image.clicked.connect(self.capture_screenshot_placeholder)
        row_img.addWidget(btn_capture_image)
        image_layout.addLayout(row_img)

        btn_generate_image = QPushButton("Generate Image")
        btn_generate_image.clicked.connect(self.generate_image_placeholder)
        image_layout.addWidget(btn_generate_image)

        # NEW BUTTON
        btn_prompt_image = QPushButton("Prompt an Image")
        btn_prompt_image.clicked.connect(self.on_prompt_image_clicked)
        image_layout.addWidget(btn_prompt_image)

        form_layout.addRow("Images:", image_layout)
        # -----------------------------------------------------------

        # -----------------------------
        # Expandable Translation Section
        # -----------------------------
        self.translation_toggle_btn = QToolButton()
        self.translation_toggle_btn.setText("Show Translations")
        self.translation_toggle_btn.setCheckable(True)
        self.translation_toggle_btn.setArrowType(Qt.RightArrow)
        self.translation_toggle_btn.clicked.connect(self.on_translation_toggled)
        form_layout.addRow("Translations:", self.translation_toggle_btn)

        self.translation_widget = QWidget()
        translation_layout = QFormLayout(self.translation_widget)
        self.field_translated_word = QLineEdit()
        translation_layout.addRow("Translated Word:", self.field_translated_word)

        self.field_translated_sentence = QPlainTextEdit()
        self.field_translated_sentence.setFixedHeight(60)
        translation_layout.addRow("Translated Sentence:", self.field_translated_sentence)

        self.btn_dictionary_search = QPushButton("Dictionary Search")
        self.btn_dictionary_search.clicked.connect(self.on_open_dictionary_search)
        translation_layout.addWidget(self.btn_dictionary_search)

        self.translation_widget.setVisible(False)
        form_layout.addRow(self.translation_widget)
        # -----------------------------

        outer_layout.addWidget(card_details_group)
        outer_layout.addSpacerItem(QSpacerItem(10, 10))
        parent_widget.setLayout(outer_layout)

        self.anki_selected_dict_form_ids = set()

    # -- NEW: Toggle the translations section
    def on_translation_toggled(self, checked):
        if checked:
            self.translation_toggle_btn.setText("Hide Translations")
            self.translation_toggle_btn.setArrowType(Qt.DownArrow)
            self.translation_widget.setVisible(True)
        else:
            self.translation_toggle_btn.setText("Show Translations")
            self.translation_toggle_btn.setArrowType(Qt.RightArrow)
            self.translation_widget.setVisible(False)

    def on_prompt_image_clicked(self):
        """
        Open a prompt for the user to enter custom text, then call
        generate_image_from_custom_prompt(prompt) if OK.
        """
        prompt_text, ok = QInputDialog.getText(self,
                                               "Prompt an Image",
                                               "Enter your custom prompt:")
        if ok and prompt_text.strip():
            self.generate_image_from_custom_prompt(prompt_text.strip())

    def generate_image_from_custom_prompt(self, prompt_text):
        """
        Generates an AI image from the given prompt_text, stores it in Anki’s media folder,
        and appends <img src="filename.png"> to self.field_image.
        """
        import os, uuid, base64, requests
        import openai
        from PyQt5.QtWidgets import QMessageBox

        if not self.openai_api_key:
            QMessageBox.warning(self, "Missing API Key",
                                "No OpenAI_API_Key is set. Please configure it first.")
            return

        if not prompt_text:
            QMessageBox.warning(self, "Empty Prompt",
                                "No prompt text provided.")
            return

        # 1) Call OpenAI with the user-specified prompt
        openai.api_key = self.openai_api_key
        try:
            response = openai.Image.create(
                prompt=prompt_text,
                n=1,
                size="512x512"  # or "1024x1024"
            )
            image_url = response["data"][0]["url"]
        except Exception as e:
            QMessageBox.warning(self, "OpenAI Error", f"Could not generate image:\n{e}")
            return

        # 2) Download the image bytes
        try:
            image_data = requests.get(image_url).content
        except Exception as e:
            QMessageBox.warning(self, "Network Error", f"Could not download image:\n{e}")
            return

        # 3) Store in Anki media
        image_filename = f"prompt_image_{uuid.uuid4().hex}.png"
        b64_data = base64.b64encode(image_data).decode("utf-8")

        res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
        if res is None:
            QMessageBox.warning(self, "Anki Error",
                                "Could not store the image in Anki’s media collection.")
            return

        # 4) Append <img src="filename.png"> to self.field_image
        new_img_tag = f'<img src="{image_filename}">'
        existing_value = self.field_image.text().strip()
        updated_value = (existing_value + " " + new_img_tag).strip()
        self.field_image.setText(updated_value)

        # 5) Inform the user
        QMessageBox.information(self, "Custom Image Created",
                                f"Successfully generated an image from your prompt.\n\n"
                                f"Prompt: {prompt_text}\n"
                                f"Saved as: {image_filename}")

    def clear_anki_editor_fields(self):
        """
        Reset all Create-Anki-Card fields to empty/default.
        """
        # For the word fields:
        self.field_native_word.clear()
        self.field_translated_word.clear()

        # For the sentence text fields:
        self.field_native_sentence.clear()
        self.field_translated_sentence.clear()

        # For the audio / image fields:
        self.field_word_audio.clear()
        self.field_sentence_audio.clear()
        self.field_image.clear()

        # For POS, we can setPlainText("") if it's a QPlainTextEdit
        self.field_pos.setPlainText("")

        # Also clear out any word checkboxes in the grid layout:
        self.clear_anki_grid_layout()
        logger.info("Cleared all Anki editor fields.")

        # Optionally reset the deck combo to some default:
        # self.deck_combo.setCurrentIndex(0)

    def on_field_image_changed(self):
        """
        Parse all <img src="..."> tags in self.field_image, and display
        each image in self.images_layout as a separate QLabel.
        """
        import re
        from PyQt5.QtGui import QPixmap

        # 1) Clear out existing preview labels
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        textval = self.field_image.text().strip()
        if not textval:
            # No images
            return

        # 2) Find all <img src="filename"> tags
        pattern = r'<img\s+src="([^"]+)">'
        matches = re.findall(pattern, textval)
        if not matches:
            return

        # 3) For each filename, create a QLabel with a 200x200 preview
        for filename in matches:
            label = QLabel()
            label.setFixedSize(200, 200)
            label.setStyleSheet("border: 1px solid gray;")
            label.setScaledContents(True)

            # Build full path inside anki_media_path
            full_path = os.path.join(self.anki_media_path, filename)
            if os.path.exists(full_path):
                pixmap = QPixmap(full_path)
                if not pixmap.isNull():
                    label.setPixmap(pixmap)
                else:
                    label.setText(f"Invalid image data: {filename}")
            else:
                label.setText(f"Missing file:\n{filename}")

            self.images_layout.addWidget(label)

    # -- NEW: Build the Dictionary Search Page (page 2 in stacked_widget)
    def build_dictionary_search_page(self, parent_widget: QWidget):
        layout = QVBoxLayout(parent_widget)
        title = QLabel("Dictionary Search")
        f = title.font()
        f.setBold(True)
        f.setPointSize(12)
        title.setFont(f)
        layout.addWidget(title)

        self.dict_search_input = QLineEdit()
        layout.addWidget(self.dict_search_input)

        self.btn_do_search = QPushButton("Search")
        self.btn_do_search.clicked.connect(self.do_dictionary_search)
        layout.addWidget(self.btn_do_search)

        self.dict_search_result = QPlainTextEdit()
        layout.addWidget(self.dict_search_result)

        # A back button to return to the card editor
        self.btn_back_to_card = QPushButton("Back to Card Editor")
        self.btn_back_to_card.clicked.connect(self.on_back_to_anki_editor)
        layout.addWidget(self.btn_back_to_card)

        parent_widget.setLayout(layout)

    # ------------------------------------------------------------------
    # Build the Word Viewer Page (page 4 in stacked_widget)
    # ------------------------------------------------------------------
    def build_word_viewer_page(self, parent_widget: QWidget):
        layout = QVBoxLayout(parent_widget)

        self.word_viewer_subtitle_label = QLabel("")
        self.word_viewer_subtitle_label.setWordWrap(True)
        layout.addWidget(self.word_viewer_subtitle_label)

        self.word_viewer_scroll = QScrollArea()
        self.word_viewer_scroll.setWidgetResizable(True)
        container = QWidget()
        self.word_viewer_layout = QHBoxLayout(container)
        self.word_viewer_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.word_viewer_scroll.setWidget(container)
        layout.addWidget(self.word_viewer_scroll)

        self.word_viewer_image_label = QLabel()
        self.word_viewer_image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.word_viewer_image_label)

        self.btn_generate_word_image = QPushButton("Generate Image")
        self.btn_generate_word_image.setEnabled(False)
        self.btn_generate_word_image.clicked.connect(self.on_generate_word_image_clicked)
        layout.addWidget(self.btn_generate_word_image)

        parent_widget.setLayout(layout)

    # -- NEW: Invoked when user clicks "Dictionary Search" in the translations
    def on_open_dictionary_search(self):
        """
        Switch from the Anki Editor toolbar actions to a single
        'Back to Card Editor' action, then show the Dictionary page.
        """
        # 1) Save the currently active Anki actions
        self._anki_actions_active = self.toolbar.actions()

        # 2) Remove them from the toolbar
        for act in self._anki_actions_active:
            self.toolbar.removeAction(act)

        # 3) Add a single action: "Back to Card Editor"
        self.action_back_to_card = QAction("Back to Card Editor", self)
        self.action_back_to_card.triggered.connect(self.on_back_to_anki_editor)
        self.toolbar.addAction(self.action_back_to_card)

        self._dictionary_actions = [self.action_back_to_card]

        # Optionally pre-fill the dictionary field
        word_to_lookup = self.field_native_word.text().strip()
        if not word_to_lookup:
            word_to_lookup = self.field_translated_word.text().strip()
        self.dict_search_input.setText(word_to_lookup)
        self.dict_search_result.clear()

        # 4) Switch to the dictionary page
        self.stacked_widget.setCurrentWidget(self.page_dictionary)

    def do_dictionary_search(self):
        # For demonstration, just show a placeholder message:
        text = self.dict_search_input.text().strip()
        if not text:
            self.dict_search_result.setPlainText("Please enter a word to search.")
            return
        # In a real app, you'd do an API or DB query here
        self.dict_search_result.setPlainText(f"Results for '{text}' (placeholder).")

    def on_back_to_anki_editor(self):
        """
        Remove the dictionary toolbar action(s), re-add the Anki Editor actions,
        and switch to the Anki Editor page.
        """
        # 1) Remove the dictionary action(s)
        for act in self._dictionary_actions:
            self.toolbar.removeAction(act)
        self._dictionary_actions.clear()

        # 2) Re-add the old Anki actions
        for act in self._anki_actions_active:
            self.toolbar.addAction(act)

        # 3) Switch to the Anki Editor page
        self.stacked_widget.setCurrentWidget(self.page_anki_editor)

    # ---------------------------------------------------------------------
    #  Called when user clicks "Create Anki Card" in the toolbar
    # ---------------------------------------------------------------------
    def on_create_anki_clicked(self):
        try:
            # 1) Attempt to sync with Anki
            self.sync_anki()
            # After sync_anki(), deck_combo is already filled with all decks.
        except Exception as e:
            logger.exception("Error syncing with Anki: %s", e)
            QMessageBox.warning(self, "Anki Sync Error", f"Could not sync with Anki:\n{e}")
            self.deck_combo.clear()
            self.deck_combo.addItem("Words")
            self.deck_combo.addItem("Study")

        # 2) Remove old toolbar actions
        self._old_actions = self.toolbar.actions()
        for act in self._old_actions:
            self.toolbar.removeAction(act)

        # 3) Create the new actions
        self.action_back_to_subs = QAction("Back to Subtitles", self)
        self.action_back_to_subs.triggered.connect(self.on_back_to_subtitles_clicked)
        self.toolbar.addAction(self.action_back_to_subs)

        self.action_add_card = QAction("Add Card", self)
        self.action_add_card.triggered.connect(self.on_add_card_triggered)
        self.toolbar.addAction(self.action_add_card)

        self.action_add_and_study = QAction("Add and Study", self)
        self.action_add_and_study.triggered.connect(self.on_add_and_study_triggered)
        self.toolbar.addAction(self.action_add_and_study)

        self._anki_actions = [
            self.action_back_to_subs,
            self.action_add_card,
            self.action_add_and_study
        ]

        # 4) Switch to the Anki Editor page
        self.stacked_widget.setCurrentIndex(1)
        self.anki_selected_dict_form_ids.clear()

        # 5) Fill fields from the currently selected subtitle line (if any)
        current_row = self.list_widget.currentRow()
        if current_row < 0 or current_row >= len(self._subtitle_lines):
            logger.info("No subtitle line selected -> Using empty editor.")
            self.field_native_sentence.setPlainText("")
            self.clear_anki_grid_layout()
            return

        start_time, end_time, text = self._subtitle_lines[current_row]
        self.field_native_sentence.setPlainText(text)
        self.display_words_for_anki_editor(text)

    def on_back_to_subtitles_clicked(self):
        print("DEBUG: Entering on_back_to_subtitles_clicked...")
        try:
            for act in self._anki_actions:
                # Only call text() if it's a QAction
                if isinstance(act, QAction):
                    print("DEBUG: Removing action:", act.text())
                    self.toolbar.removeAction(act)
                elif isinstance(act, QWidgetAction):
                    print("DEBUG: Removing QWidgetAction (spacer)")
                    self.toolbar.removeAction(act)
                else:
                    print("DEBUG: Removing unknown object:", act)

            self._anki_actions.clear()
            for old_act in self._old_actions:
                self.toolbar.addAction(old_act)

            self.clear_anki_editor_fields()

            self.stacked_widget.setCurrentIndex(0)


            print("DEBUG: Finished on_back_to_subtitles_clicked OK.")
        except Exception as e:
            print("DEBUG: Exception in on_back_to_subtitles_clicked:", e)

    def on_add_card_triggered(self):
        """
        Called when user clicks 'Add Card' in the Anki Editor toolbar.
        1) Gather fields from the UI.
        2) Build a 'card' dict similar to your import logic (with ...["value"]).
        3) If the chosen deck is 'Words' or 'Study', we also parse the card
           and store it in the local DB (as your example code does).
           Otherwise, we just create the note in Anki.
        """
        chosen_deck = self.deck_combo.currentText().strip()
        if not chosen_deck:
            QMessageBox.warning(self, "No Deck Selected", "Please choose a deck before adding a card.")
            return

        # -----------------------------------------------------------------
        # 1) Gather field data from the UI (these match your snippet fields)
        # -----------------------------------------------------------------
        native_word_str = self.field_native_word.text().strip()
        native_sentence_str = self.field_native_sentence.toPlainText().strip()
        translated_word_str = self.field_translated_word.text().strip()
        translated_sentence_str = self.field_translated_sentence.toPlainText().strip()
        pos_value = self.field_pos.toPlainText().strip()
        word_audio_value = self.field_word_audio.text().strip()
        sentence_audio_value = self.field_sentence_audio.text().strip()
        image_html = self.field_image.text().strip()

        # If you have a separate "reading" field in your UI,
        # collect that here; else set blank:
        reading_str = ""  # or self.field_reading.text().strip()

        # We can store the chosen deck name in the "deck_name" field
        # so your old code can tag it, etc.
        deck_name = chosen_deck

        # -----------------------------------------------------------------
        # 2) Build a single 'card' dict matching your import structure
        # -----------------------------------------------------------------
        card_data = {
            "native word": {"value": native_word_str},
            "native sentence": {"value": native_sentence_str},
            "translated word": {"value": translated_word_str},
            "translated sentence": {"value": translated_sentence_str},
            "pos": {"value": pos_value},
            "word audio": {"value": word_audio_value},
            "sentence audio": {"value": sentence_audio_value},
            "image": {"value": image_html},
            "reading": {"value": reading_str},
            # This helps your snippet code generate tags, etc.
            "deck_name": deck_name
        }

        # -----------------------------------------------------------
        # 3) If the chosen deck is 'Words' or 'Study':
        #    - We do EXACTLY what your snippet does: morphological
        #      parse, local DB insert, and also create the note in Anki.
        #
        #    If the chosen deck is NOT 'Words'/'Study':
        #    - We simply create the note in Anki (but skip local parse).
        # -----------------------------------------------------------
        if chosen_deck in ("Words", "Study"):
            # Reuse your existing "insert_imported_cards_into_db" approach,
            # but we need it to honor chosen_deck as the target in Anki
            # instead of forcibly using "Words".
            #
            # One way: create a new method that is almost identical to
            # insert_imported_cards_into_db, except it calls:
            #   self.anki.add_note(chosen_deck, "CSRS", note_type_fields, tags=tags)
            # instead of always using "Words".
            #
            # For demo, let's define a quick variant here:

            self.insert_single_card_into_db_and_anki(card_data, chosen_deck)
            QMessageBox.information(self, "Card Created",
                                    f"A new card has been added to your '{chosen_deck}' deck, "
                                    "and stored in the local db_manager.")
        else:
            # Just create the Anki note, skip local DB parse
            note_type_fields = {
                # match the keys from your "CSRS" model
                "native word": native_word_str,
                "native sentence": native_sentence_str,
                "translated word": translated_word_str,
                "translated sentence": translated_sentence_str,
                "pos": pos_value,
                "word audio": word_audio_value,
                "sentence audio": sentence_audio_value,
                "image": image_html,
                "reading": reading_str
            }
            tags = ["created_via_subtitles", deck_name]

            note_id = self.anki.add_note(chosen_deck, "CSRS", note_type_fields, tags=tags)
            if note_id is None:
                QMessageBox.warning(self, "Anki Error",
                                    "Failed to add note to Anki (no note_id returned).")
                return

            QMessageBox.information(self, "Card Created",
                                    f"A new card has been added to Anki deck '{chosen_deck}' (no DB parse).")

    def insert_single_card_into_db_and_anki(self, card: dict, chosen_deck: str):
        """
        A single-card version of your 'insert_imported_cards_into_db' logic.
        Creates the note in the chosen deck (not hard-coded to 'Words'),
        then does morphological parse, local DB insert, etc.
        """
        from content_parser import ContentParser
        parser = ContentParser()

        # Example code similar to your snippet, but just for one card:
        native_word_str = card.get("native word", {}).get("value", "").strip()
        native_sentence_str = card.get("native sentence", {}).get("value", "").strip()
        translated_word_str = card.get("translated word", {}).get("value", "").strip()
        translated_sentence_str = card.get("translated sentence", {}).get("value", "").strip()
        reading_str = card.get("reading", {}).get("value", "").strip()
        pos_value = card.get("pos", {}).get("value", "").strip()
        word_audio_value = card.get("word audio", {}).get("value", "").strip()
        sentence_audio_value = card.get("sentence audio", {}).get("value", "").strip()
        image_html = card.get("image", {}).get("value", "").strip()

        deck_name = card.get("deck_name", chosen_deck)  # fallback

        # Tagging
        tags = ["anki_deck", deck_name]

        # Build the note fields for Anki:
        note_type_fields = {
            "native word": native_word_str,
            "translated word": translated_word_str,
            "word audio": word_audio_value,
            "pos": pos_value,
            "native sentence": native_sentence_str,
            "translated sentence": translated_sentence_str,
            "sentence audio": sentence_audio_value,
            "image": image_html,
            "reading": reading_str,
        }

        # Create the note in Anki => returns note_id
        note_id = self.anki.add_note(chosen_deck, "CSRS", note_type_fields, tags=tags)
        if note_id is None:
            logger.warning("Could not add note to Anki for card: %s", card)
            return

        # Retrieve the newly created card's ID (should be 1 per note in this model)
        card_ids = self.anki.find_cards(f"nid:{note_id}")
        if not card_ids:
            logger.warning("No card_ids found for newly created note_id: %s", note_id)
            return

        anki_card_id = card_ids[0]

        # Insert local DB row.
        # Using your example DB calls:
        words_deck_id = self.db_manager.get_deck_id_by_name(chosen_deck)
        if not words_deck_id:
            # Or create if missing:
            words_deck_id = self.db_manager.ensure_Words_deck_exists()

        text_id = self.db_manager.add_text_source(deck_name, "manual_add")
        sentence_id = self.db_manager.add_sentence_if_not_exist(text_id, native_sentence_str)

        card_id = self.db_manager.add_card(
            deck_id=words_deck_id,
            anki_card_id=anki_card_id,
            deck_origin=deck_name,  # e.g. "Words", "Study", etc.
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

        # Morphological parse of the sentence
        tokens = parser.parse_content(native_sentence_str)
        for tk in tokens:
            dict_form_id = self.db_manager.get_or_create_dictionary_form(
                base_form=tk["base_form"],
                reading=tk["reading"],
                pos=tk["pos"]
            )
            self.db_manager.add_surface_form(
                dict_form_id=dict_form_id,
                surface_form=tk["surface_form"],
                reading=tk["reading"],
                pos=tk["pos"],
                sentence_id=sentence_id,
                card_id=card_id
            )

        self.update_unknown_count_for_sentence(sentence_id)
        self.db_manager.update_card_tags(card_id, [deck_name])  # tag in DB

        logger.info("Inserted single card into local DB + Anki deck '%s'.", chosen_deck)

    def on_add_and_study_triggered(self):
        QMessageBox.information(self, "Add and Study", "Add and Study triggered (placeholder).")

    def update_unknown_count_for_sentence(self, sentence_id):
        cur = self.db_manager._conn.cursor()
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
        self.db_manager._conn.commit()

    def display_words_for_anki_editor(self, subtitle_text: str):
        self.clear_anki_grid_layout()
        if not self.db_manager:
            return

        forms = self.db_manager.get_surface_forms_for_text_content(subtitle_text)
        if not forms:
            no_label = QLabel("No words found for this line.")
            self.anki_grid_layout.addWidget(no_label, 0, 0, 1, 1)
            return

        label_select = QLabel("Select")
        label_select.setAlignment(Qt.AlignRight)
        label_select.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.anki_grid_layout.addWidget(label_select, 2, 0)

        for col_index, (sf_id, surface, df_id, base_form, known) in enumerate(forms, start=1):
            word_label = QLabel(surface)
            word_label.setAlignment(Qt.AlignCenter)
            self.anki_grid_layout.addWidget(word_label, 0, col_index)
            word_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            self.grid_layout.setRowStretch(0, 1)
            logger.info("word_label font:", word_label.font().pointSize())

            reading_label = QLabel(f"({base_form})")
            reading_label.setAlignment(Qt.AlignCenter)
            self.anki_grid_layout.addWidget(reading_label, 1, col_index)

            cb = QCheckBox("")
            cb.setChecked(False)
            cb.stateChanged.connect(
                lambda state, d_id=df_id, s_text=surface: self.on_anki_word_checkbox_changed(d_id, s_text, state)
            )
            self.anki_grid_layout.addWidget(cb, 2, col_index, alignment=Qt.AlignHCenter)




        total_cols = len(forms) + 1
        for c in range(total_cols):
            self.anki_grid_layout.setColumnStretch(c, 0)



    def clear_anki_grid_layout(self):
        while self.anki_grid_layout.count():
            item = self.anki_grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def sync_anki(self):
        """
        Fetch all decks from AnkiConnect and pass them directly to the combo box.
        """
        try:
            # 1) Get decks from Anki
            current_decks = self.anki.get_decks()  # could be a dict or list
            if not current_decks:
                QMessageBox.warning(self, "No Decks Found", "Anki returned no decks.")
                return

            # 2) Convert them to a simple list of deck names
            if isinstance(current_decks, dict):
                deck_list = list(current_decks.keys())
            else:
                deck_list = list(current_decks)

            # (Optional) sort them
            deck_list.sort()

            # 3) Populate self.deck_combo
            self.deck_combo.clear()
            for deck_name in deck_list:
                self.deck_combo.addItem(deck_name)

            logger.info(f"Populated deck_combo with {len(deck_list)} decks: {deck_list}")

        except Exception as e:
            logger.exception("Error while syncing Anki decks")
            QMessageBox.warning(self, "Anki Error", f"Could not retrieve decks:\n{e}")

    def on_anki_word_checkbox_changed(self, dict_form_id, surface_text, state):
        checked = (state == Qt.Checked)
        if checked:
            self.anki_selected_dict_form_ids.add(dict_form_id)
            # Store the SURFACE form for this df_id
            self.anki_selected_dict_form_surfaces[dict_form_id] = surface_text
        else:
            self.anki_selected_dict_form_ids.discard(dict_form_id)
            # Remove the surface if unchecked
            self.anki_selected_dict_form_surfaces.pop(dict_form_id, None)

        self.update_anki_fields_from_selection()

    def update_anki_fields_from_selection(self):
        """
        Collect all selected dictionary-form IDs, fetch their SURFACE forms,
        and display them in the "Native Word" field.
        """
        if not self.db_manager:
            return

        selected_surfaces = []
        pos_list = []

        for df_id in self.anki_selected_dict_form_ids:
            # 1) The surface form was cached in our dict:
            surf = self.anki_selected_dict_form_surfaces.get(df_id, "")
            selected_surfaces.append(surf)

            # 2) If you also want to gather POS from the DB:
            info = self.db_manager.get_dict_form_info(df_id)
            if info:
                pos = info.get("pos", "")
                pos_list.append(pos)

        # e.g. "食べた, 飲んだ"
        joined_surfaces = ", ".join(selected_surfaces)
        # e.g. "Verb, Verb"
        joined_pos = ", ".join(pos_list)

        # Now put that into the "native word" field:
        self.field_native_word.setText(joined_surfaces)
        self.field_pos.setPlainText(joined_pos)

    # ---------------------------------------------------------------------
    #  Placeholder Methods for Buttons
    # ---------------------------------------------------------------------
    def play_word_audio_placeholder(self):
        """
        Attempt to parse the [sound:filename] from self.field_word_audio
        and play it via self.audio_player (which should be a QMediaPlayer).
        """
        import re
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QMediaContent

        audio_tag = self.field_word_audio.text().strip()
        match = re.search(r'\[sound:(.*?)\]', audio_tag)
        if not match:
            QMessageBox.warning(self, "No Sound Tag", "No [sound:filename] found in the Word Audio field.")
            return

        filename = match.group(1)
        # This requires knowledge of your Anki media path
        full_path = os.path.join(self.anki_media_path, filename)
        if not os.path.exists(full_path):
            QMessageBox.warning(self, "File Missing", f"Audio file not found:\n{full_path}")
            return

        # Use QMediaPlayer
        self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(full_path)))
        self.audio_player.play()

        QMessageBox.information(self, "Playing Word Audio", f"Now playing: {filename}")

    def generate_word_audio_placeholder(self):
        """
        Generate word audio via Google TTS and store the resulting MP3
        either in Anki or in your local system. This example stores in Anki
        (similar to main.py) so it requires 'self.anki' to be a valid AnkiConnector.
        """

        import os
        # 1) Get the text we want to TTS.
        #    Replace 'self.field_native_word.text()' with wherever you keep the target word.
        word_text = self.field_native_word.text().strip()
        if not word_text:
            QMessageBox.warning(self, "No Word", "Please enter or select a word to generate audio.")
            return

        # 2) Ensure we have Google TTS credentials
        if not os.path.exists(self.google_credentials):
            QMessageBox.warning(self, "Missing Credentials", "No Google TTS credentials found.")
            return

        # 3) Actually call Google TTS
        import os, uuid, base64
        from google.cloud import texttospeech

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials
        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text=word_text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
        )
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

        try:
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
        except Exception as e:
            QMessageBox.warning(self, "TTS Error", f"Failed to generate TTS audio:\n{e}")
            return

        # 4) Store the audio in Anki media (or local)
        audio_filename = f"word_audio_{uuid.uuid4().hex}.mp3"
        b64_data = base64.b64encode(response.audio_content).decode("utf-8")

        # Store via AnkiConnect:
        res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
        if res is None:
            QMessageBox.warning(self, "Anki Error", "Could not store TTS result in Anki media.")
            return

        # 5) Build the [sound:filename] tag
        new_sound_tag = f"[sound:{audio_filename}]"

        # 6) Optionally update a QLineEdit or your DB with this new sound tag
        self.field_word_audio.setText(new_sound_tag)

        QMessageBox.information(self, "Audio Generated", f"Generated word audio for '{word_text}'!")

    def play_sentence_audio_placeholder(self):
        import re
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QMediaContent

        audio_tag = self.field_sentence_audio.text().strip()
        match = re.search(r'\[sound:(.*?)\]', audio_tag)
        if not match:
            QMessageBox.warning(self, "No Sound Tag", "No [sound:filename] found in the Sentence Audio field.")
            return

        filename = match.group(1)
        full_path = os.path.join(self.anki_media_path, filename)
        if not os.path.exists(full_path):
            QMessageBox.warning(self, "File Missing", f"Audio file not found:\n{full_path}")
            return

        self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(full_path)))
        self.audio_player.play()

    def capture_sentence_audio_placeholder(self):
        """
        Capture the audio for the currently selected subtitle range,
        store it in Anki’s media folder,
        then APPEND the resulting [sound:filename] tag in self.field_sentence_audio.
        """
        import os
        import uuid
        import base64
        import subprocess
        import tempfile
        import shutil
        from PyQt5.QtWidgets import QMessageBox

        print("[DEBUG] Entering capture_sentence_audio_placeholder...")

        # 1) Identify the subtitle line or index we want to capture
        index = self._last_active_index
        print(f"[DEBUG] current subtitle index: {index}")
        if index < 0 or index >= len(self._subtitle_lines):
            print("[DEBUG] No valid subtitle selected (index out of range).")
            QMessageBox.warning(self, "No Subtitle Selected", "No valid subtitle is selected.")
            return

        start_sec, end_sec, text = self._subtitle_lines[index]
        print(f"[DEBUG] subtitle range: start={start_sec}, end={end_sec}, text='{text}'")
        if end_sec <= start_sec:
            print("[DEBUG] Invalid start/end range.")
            QMessageBox.warning(self, "Invalid Range", "Subtitle start/end times are invalid.")
            return

        # 2) Get the current video path
        if not self.get_current_video_path:
            print("[DEBUG] get_current_video_path callback is None.")
            QMessageBox.warning(self, "No Video Reference", "Cannot capture audio without a video path reference.")
            return

        try:
            possible_mpv_uri = self.get_current_video_path()
        except Exception as e:
            print(f"[DEBUG] get_current_video_path() threw an exception: {e}")
            QMessageBox.warning(self, "Video Path Error", f"Error fetching video path:\n{e}")
            return

        print(f"[DEBUG] possible_mpv_uri from get_current_video_path(): {possible_mpv_uri}")

        # Convert MPV URI to plain OS path if needed
        media_file = possible_mpv_uri
        if media_file.startswith("file://"):
            media_file = self.db_manager.mpv_path_to_file_path(media_file)

        print(f"[DEBUG] Final media_file for ffmpeg: {media_file}")
        if not media_file or not os.path.exists(media_file):
            print(f"[DEBUG] media_file does not exist: {media_file}")
            QMessageBox.warning(self, "File Not Found", f"Video file does not exist:\n{media_file}")
            return

        # 3) Unique name for snippet
        audio_filename = f"sentence_audio_{uuid.uuid4().hex}.mp3"
        audio_out_path = os.path.join(self.anki_media_path, audio_filename)
        print(f"[DEBUG] audio_filename={audio_filename}")
        print(f"[DEBUG] audio_out_path={audio_out_path}")

        # 4) Use ffmpeg to extract the snippet
        print("[DEBUG] Starting ffmpeg extraction...")
        try:
            temp_audio_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_audio_path = temp_audio_file.name
            temp_audio_file.close()

            print(f"[DEBUG] temp_audio_path={temp_audio_path}")

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-to", str(end_sec),
                "-i", media_file,
                "-map", "0:a",
                "-acodec", "libmp3lame",
                temp_audio_path
            ]

            print("[DEBUG] ffmpeg command:")
            print(" ".join(cmd))

            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            print(f"[DEBUG] ffmpeg returncode={result.returncode}")
            if result.stdout:
                print(f"[DEBUG] ffmpeg stdout:\n{result.stdout}")
            if result.stderr:
                print(f"[DEBUG] ffmpeg stderr:\n{result.stderr}")

            if result.returncode != 0:
                print("[DEBUG] ffmpeg returned non-zero status.")
                QMessageBox.warning(self, "FFmpeg Error", "Failed to extract audio snippet with ffmpeg.")
                return

            if not os.path.exists(temp_audio_path):
                print(f"[DEBUG] ffmpeg did not produce file at {temp_audio_path}")
                QMessageBox.warning(self, "Audio Error", "ffmpeg did not produce the output MP3.")
                return

            print(f"[DEBUG] Moving temp audio to {audio_out_path}")
            shutil.move(temp_audio_path, audio_out_path)

        except Exception as e:
            print(f"[DEBUG] Exception during ffmpeg extraction: {e}")
            QMessageBox.warning(self, "Extraction Error", f"Error extracting audio:\n{e}")
            return

        # 5) Store in Anki if needed
        print("[DEBUG] Attempting to store in Anki media collection...")
        try:
            with open(audio_out_path, "rb") as f:
                audio_data = f.read()
            b64_data = base64.b64encode(audio_data).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=audio_filename, data=b64_data)
            if res is None:
                print("[DEBUG] storeMediaFile returned None; unable to store in Anki.")
                QMessageBox.warning(self, "Anki Error", "Could not store snippet in Anki’s media collection.")
                return

            # 6) Build the new sound tag
            new_sound_tag = f"[sound:{audio_filename}]"
            print(f"[DEBUG] Created new sound tag: {new_sound_tag}")

            # =========== ONLY APPEND ONCE =============
            existing_audio_tags = self.field_sentence_audio.text().strip()
            print(f"[DEBUG] existing_audio_tags BEFORE appending: {repr(existing_audio_tags)}")

            if existing_audio_tags:
                updated_field_value = existing_audio_tags + " " + new_sound_tag
            else:
                updated_field_value = new_sound_tag

            print(f"[DEBUG] updated_field_value AFTER appending: {repr(updated_field_value)}")
            self.field_sentence_audio.setText(updated_field_value)
            # =========== DONE APPENDING ==============

            QMessageBox.information(
                self,
                "Audio Captured",
                f"Captured subtitle audio:\n{start_sec:.2f} - {end_sec:.2f}"
            )

        except Exception as e:
            print(f"[DEBUG] Exception during Anki storeMediaFile step: {e}")
            QMessageBox.warning(self, "Anki Error", f"Error storing snippet in Anki:\n{e}")

        print("[DEBUG] Exiting capture_sentence_audio_placeholder normally.")

    def get_current_video_path(self) -> str:
        """
        Use the *currently selected* subtitle line (start, end, text),
        query the DB for a matching row in sentences, and find the media.file_path
        or media.mpv_path.

        Raises ValueError if not found or if not unique.
        """
        if self._last_active_index < 0 or self._last_active_index >= len(self._subtitle_lines):
            raise ValueError("No valid subtitle line is selected.")

        start_sec, end_sec, text = self._subtitle_lines[self._last_active_index]

        # Query the DB using the triple (start_time, end_time, text)
        query = """
        SELECT sub.media_id
          FROM subtitles sub
          JOIN texts t ON sub.subtitle_file = t.source
          JOIN sentences s ON s.text_id = t.text_id
         WHERE s.start_time = ?
           AND s.end_time   = ?
           AND s.content    = ?
         LIMIT 1
        """
        cur = self.db_manager._conn.cursor()
        cur.execute(query, (start_sec, end_sec, text))
        row = cur.fetchone()
        if not row:
            raise ValueError("Could not find a matching media_id in the DB for that subtitle line.")

        media_id = row[0]

        # Now fetch the actual path from media
        media_info = self.db_manager.get_media_info(media_id)
        if not media_info:
            raise ValueError(f"No media info found for media_id={media_id}.")

        file_path = media_info["file_path"]  # e.g. '\\desktop\Shared Files2\Show01.mkv'
        if not file_path:
            raise ValueError(f"Media ID {media_id} does not have a valid file_path in the db_manager.")

        return file_path

    def play_sentence_audio_all(self):
        """
        Finds all [sound:filename.mp3] tags in field_sentence_audio,
        and plays them in sequence using self.audio_player.
        """
        import re
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QMediaContent

        # 1) Extract each [sound:filename.mp3] from the field
        text = self.field_sentence_audio.text()
        pattern = r'\[sound:(.*?)\]'
        sound_files = re.findall(pattern, text)
        if not sound_files:
            print("No [sound:...] tags found in the sentence audio field.")
            return

        print(f"Found sound files: {sound_files}")

        # 2) Convert each to the full path in your anki_media_path
        full_paths = []
        for sf in sound_files:
            # If the user stored them in self.anki_media_path
            # e.g. sf = 'sentence_audio_abc123.mp3'
            file_path = os.path.join(self.anki_media_path, sf)
            if os.path.exists(file_path):
                full_paths.append(file_path)
            else:
                print(f"Missing audio file: {file_path}")

        if not full_paths:
            print("No local files found to play.")
            return

        # 3) Option A: Use a simple approach: play the first, then when that finishes,
        #    move to the next. We connect a signal to handle the "finished" event.
        #    QMediaPlayer doesn’t have a built-in queue, but we can do it manually.

        self._current_sound_index = 0
        self._sound_playlist = full_paths[:]  # copy

        # Connect to the player’s stateChanged signal if not already:
        self.audio_player.stateChanged.connect(self.on_audio_state_changed)

        # Start playing the first
        self.play_next_sound_in_sequence()

    def play_next_sound_in_sequence(self):
        """
        Plays the sound file at self._sound_playlist[self._current_sound_index].
        """
        if not hasattr(self, '_sound_playlist'):
            return
        if self._current_sound_index >= len(self._sound_playlist):
            print("All sounds played.")
            return

        next_file = self._sound_playlist[self._current_sound_index]
        print(f"Playing: {next_file}")
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QMediaContent

        self.audio_player.setMedia(QMediaContent(QUrl.fromLocalFile(next_file)))
        self.audio_player.play()

    def on_audio_state_changed(self, new_state):
        """
        Called whenever QMediaPlayer changes state.
        If it transitions to StoppedState, we try the next audio file.
        """
        from PyQt5.QtMultimedia import QMediaPlayer
        if new_state == QMediaPlayer.StoppedState:
            # Move to next file
            if hasattr(self, '_sound_playlist') and self._sound_playlist:
                self._current_sound_index += 1
                if self._current_sound_index < len(self._sound_playlist):
                    self.play_next_sound_in_sequence()
                else:
                    print("Finished playing all queued sounds.")

    def capture_screenshot_placeholder(self):
        """
        Capture a screenshot from the current video around the midpoint of the
        selected subtitle range, store it in Anki’s media folder,
        and append a <img src="filename.png"> to a target field (like self.field_image).
        """
        import os
        import uuid
        import base64
        import subprocess
        import tempfile
        import shutil
        from PyQt5.QtWidgets import QMessageBox

        print("[DEBUG] Entering capture_screenshot_placeholder...")

        # 1) Identify current subtitle line
        index = self._last_active_index
        print(f"[DEBUG] current subtitle index: {index}")
        if index < 0 or index >= len(self._subtitle_lines):
            print("[DEBUG] No valid subtitle selected (index out of range).")
            QMessageBox.warning(self, "No Subtitle Selected", "No valid subtitle is selected.")
            return

        start_sec, end_sec, text = self._subtitle_lines[index]
        print(f"[DEBUG] subtitle range: start={start_sec}, end={end_sec}, text='{text}'")
        if end_sec <= start_sec:
            print("[DEBUG] Invalid start/end range.")
            QMessageBox.warning(self, "Invalid Range", "Subtitle start/end times are invalid.")
            return

        # 2) Get the current video path
        if not self.get_current_video_path:
            print("[DEBUG] get_current_video_path callback is None.")
            QMessageBox.warning(self, "No Video Reference", "Cannot capture screenshot without a video reference.")
            return

        try:
            possible_mpv_uri = self.get_current_video_path()
        except Exception as e:
            print(f"[DEBUG] get_current_video_path() threw an exception: {e}")
            QMessageBox.warning(self, "Video Path Error", f"Error fetching video path:\n{e}")
            return

        print(f"[DEBUG] possible_mpv_uri from get_current_video_path(): {possible_mpv_uri}")

        # Convert MPV URI to plain OS path if needed
        media_file = possible_mpv_uri
        if media_file.startswith("file://"):
            media_file = self.db_manager.mpv_path_to_file_path(media_file)

        print(f"[DEBUG] Final media_file for ffmpeg screenshot: {media_file}")
        if not media_file or not os.path.exists(media_file):
            print(f"[DEBUG] media_file does not exist: {media_file}")
            QMessageBox.warning(self, "File Not Found", f"Video file does not exist:\n{media_file}")
            return

        # 3) Construct a unique name for the screenshot (e.g., .png or .jpg)
        image_filename = f"sentence_img_{uuid.uuid4().hex}.png"
        image_out_path = os.path.join(self.anki_media_path, image_filename)
        print(f"[DEBUG] image_filename={image_filename}")
        print(f"[DEBUG] image_out_path={image_out_path}")

        # 4) ffmpeg: capture a single frame at the midpoint
        midpoint_sec = (start_sec + end_sec) / 2.0
        print(f"[DEBUG] midpoint time for screenshot: {midpoint_sec}")

        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(midpoint_sec),
                "-i", media_file,
                "-vframes", "1",
                "-filter:v", "scale=400:-1",  # 400 wide, keep aspect ratio
                image_out_path
            ]

            print("[DEBUG] ffmpeg screenshot command:")
            print(" ".join(cmd))

            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            print(f"[DEBUG] ffmpeg returncode={result.returncode}")
            if result.stdout:
                print(f"[DEBUG] ffmpeg stdout:\n{result.stdout}")
            if result.stderr:
                print(f"[DEBUG] ffmpeg stderr:\n{result.stderr}")

            if result.returncode != 0:
                print("[DEBUG] ffmpeg returned non-zero status.")
                QMessageBox.warning(self, "FFmpeg Error", "Failed to capture screenshot with ffmpeg.")
                return

            if not os.path.exists(image_out_path):
                print("[DEBUG] ffmpeg did not produce the image file.")
                QMessageBox.warning(self, "Screenshot Error", "ffmpeg did not produce the image file.")
                return

        except Exception as e:
            print(f"[DEBUG] Exception during ffmpeg screenshot: {e}")
            QMessageBox.warning(self, "Extraction Error", f"Error capturing screenshot:\n{e}")
            return

        # 5) Optionally store in Anki
        print("[DEBUG] Attempting to store screenshot in Anki media collection...")
        try:
            with open(image_out_path, "rb") as f:
                image_data = f.read()
            b64_data = base64.b64encode(image_data).decode("utf-8")

            res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
            if res is None:
                print("[DEBUG] storeMediaFile returned None; unable to store in Anki.")
                QMessageBox.warning(self, "Anki Error", "Could not store screenshot in Anki’s media collection.")
                return

            # 6) Build the <img src="filename.png"> tag
            new_img_tag = f'<img src="{image_filename}">'
            print(f"[DEBUG] Created new img tag: {new_img_tag}")

            # 7) Append multiple screenshots in the same field (self.field_image)
            #    If you have a QLineEdit or QPlainTextEdit, do something like:
            existing_value = self.field_image.text().strip()  # or self.field_image.toPlainText().strip()
            print(f"[DEBUG] existing_value BEFORE appending: {repr(existing_value)}")

            if existing_value:
                updated_value = existing_value + " " + new_img_tag
            else:
                updated_value = new_img_tag

            self.field_image.setText(updated_value)  # or setPlainText(updated_value)
            print(f"[DEBUG] field_image updated_value: {repr(updated_value)}")

            QMessageBox.information(
                self,
                "Screenshot Captured",
                f"Captured screenshot at ~{midpoint_sec:.2f} seconds."
            )

        except Exception as e:
            print(f"[DEBUG] Exception during Anki storeMediaFile step: {e}")
            QMessageBox.warning(self, "Anki Error", f"Error storing screenshot in Anki:\n{e}")

        print("[DEBUG] Exiting capture_screenshot_placeholder normally.")

    def generate_image_placeholder(self):
        """
        Generate an AI image from the current subtitle text, store it in Anki media,
        and append a <img src="filename.png"> to self.field_image.
        """
        import os, uuid, base64, requests
        import openai
        from PyQt5.QtWidgets import QMessageBox

        # 1) Check we have a key
        if not self.openai_api_key:
            QMessageBox.warning(self, "Missing API Key",
                                "No OpenAI_API_Key is set. Please configure it first.")
            return

        # 2) Select the subtitle text (or use self.field_native_sentence)
        index = self._last_active_index
        if index < 0 or index >= len(self._subtitle_lines):
            QMessageBox.warning(self, "No Subtitle Selected",
                                "Cannot generate an image without a valid subtitle.")
            return

        start_sec, end_sec, text = self._subtitle_lines[index]
        if not text.strip():
            QMessageBox.warning(self, "Empty Text",
                                "The selected subtitle text is empty.")
            return

        # 3) Call OpenAI
        openai.api_key = self.openai_api_key
        prompt = (
            f"Create a clear, literal, and intuitive illustration that visually conveys the core meaning of the word or phrase '{text}'. "
            f"Your illustration must depict a realistic scene or scenario where the meaning of '{text}' can be easily understood at a glance, without requiring textual explanation. "
            f"Include visual cues such as relevant actions, emotions, context, and appropriate background elements. "
            f"Clearly focus on expressing the central concept or idea behind '{text}'. "
            f"Avoid ambiguity or overly abstract visuals; instead, prioritize clarity, realism, and immediate comprehension suitable for language learners."
        )
        try:
            response = openai.Image.create(
                prompt=prompt,
                n=1,
                size="1024x1024",  # or "1024x1024",
                model= "dall-e-3"  # Specify the DALL-E 3 model for HD
            )
            image_url = response["data"][0]["url"]
        except Exception as e:
            QMessageBox.warning(self, "OpenAI Error", f"Could not generate image:\n{e}")
            return

        # 4) Download the image data
        try:
            image_data = requests.get(image_url).content
        except Exception as e:
            QMessageBox.warning(self, "Network Error", f"Could not download image:\n{e}")
            return

        # 5) Store in Anki media
        image_filename = f"ai_image_{uuid.uuid4().hex}.png"
        b64_data = base64.b64encode(image_data).decode("utf-8")
        res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
        if res is None:
            QMessageBox.warning(self, "Anki Error",
                                "Could not store the image in Anki’s media collection.")
            return

        # 6) Append <img src=...> to self.field_image
        new_img_tag = f'<img src="{image_filename}">'
        existing_value = self.field_image.text().strip()
        updated_value = (existing_value + " " + new_img_tag).strip()
        self.field_image.setText(updated_value)

        QMessageBox.information(self, "Image Generated",
                                f"Created AI image for subtitle:\n{text}\n"
                                f"File saved as: {image_filename}")

    # ------------------------------------------------------------------
    # Word Viewer helpers
    # ------------------------------------------------------------------
    def populate_word_viewer(self, subtitle_text: str):
        """Fill the word viewer page with words from subtitle_text."""
        self.word_viewer_subtitle_label.setText(subtitle_text)
        while self.word_viewer_layout.count():
            item = self.word_viewer_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.selected_word_id = None
        self.selected_word_text = ""
        self.selected_word_label = None
        self.btn_generate_word_image.setEnabled(False)
        self.word_viewer_image_label.clear()

        if not self.db_manager:
            return

        forms = self.db_manager.get_surface_forms_for_text_content(subtitle_text)
        if not forms:
            self.word_viewer_layout.addWidget(QLabel("No words found for this subtitle."))
            return

        for (sf_id, surface, df_id, base_form, known) in forms:
            cont = QWidget()
            vbox = QVBoxLayout(cont)
            lbl_word = ClickableWordLabel(surface, df_id)
            base_lbl = QLabel(f"({base_form})")
            lbl_word.clicked.connect(lambda w=surface, d=df_id, l=lbl_word: self.on_word_label_clicked(w, d, l))
            vbox.addWidget(lbl_word, alignment=Qt.AlignCenter)
            vbox.addWidget(base_lbl, alignment=Qt.AlignCenter)
            cont.setLayout(vbox)
            self.word_viewer_layout.addWidget(cont)

    def on_word_label_clicked(self, word_text: str, dict_form_id: int, label: QLabel):
        if self.selected_word_label is not None:
            self.selected_word_label.setStyleSheet("")
        self.selected_word_label = label
        self.selected_word_id = dict_form_id
        self.selected_word_text = word_text
        label.setStyleSheet("background-color: yellow;")
        self.btn_generate_word_image.setEnabled(True)

    def on_generate_word_image_clicked(self):
        if not self.selected_word_text:
            QMessageBox.warning(self, "No Word Selected", "Please select a word first.")
            return

        self.generate_image_for_word(self.selected_word_text)

    def generate_image_for_word(self, word_text: str):
        """Generate an image using OpenAI for the given word_text and display it."""
        import os, uuid, base64, requests, openai

        if not self.openai_api_key:
            QMessageBox.warning(self, "Missing API Key", "No OpenAI_API_Key is set. Please configure it first.")
            return

        prompt = (
            f"Create a clear, literal, and intuitive illustration that visually conveys the core meaning of the word or phrase '{word_text}'. "
            f"Your illustration must depict a realistic scene or scenario where the meaning of '{word_text}' can be easily understood at a glance, without requiring textual explanation. "
            f"Include visual cues such as relevant actions, emotions, context, and appropriate background elements. "
            f"Clearly focus on expressing the central concept or idea behind '{word_text}'. "
            f"Avoid ambiguity or overly abstract visuals; instead, prioritize clarity, realism, and immediate comprehension suitable for language learners."
        )

        openai.api_key = self.openai_api_key
        try:
            response = openai.Image.create(prompt=prompt, n=1, size="512x512")
            image_url = response["data"][0]["url"]
        except Exception as e:
            QMessageBox.warning(self, "OpenAI Error", f"Could not generate image:\n{e}")
            return

        try:
            image_data = requests.get(image_url).content
        except Exception as e:
            QMessageBox.warning(self, "Network Error", f"Could not download image:\n{e}")
            return

        image_filename = f"word_image_{uuid.uuid4().hex}.png"
        b64_data = base64.b64encode(image_data).decode("utf-8")
        res = self.anki.invoke("storeMediaFile", filename=image_filename, data=b64_data)
        if res is None:
            QMessageBox.warning(self, "Anki Error", "Could not store the image in Anki’s media collection.")
            return

        full_path = os.path.join(self.anki_media_path, image_filename)
        if os.path.exists(full_path):
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                self.word_viewer_image_label.setPixmap(pixmap.scaledToWidth(300, Qt.SmoothTransformation))
        QMessageBox.information(self, "Image Generated", f"Created AI image for word: {word_text}\nSaved as: {image_filename}")
