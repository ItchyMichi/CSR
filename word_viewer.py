from PyQt5.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt, pyqtSignal, QThreadPool

class WordViewerWindow(QDialog):
    openVideoAtTime = pyqtSignal(int, float)  # media_id, timestamp

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Word Viewer")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        self.layout = QVBoxLayout(self)
        self.word_list = QListWidget(self)
        self.layout.addWidget(self.word_list)
        self.thread_pool = QThreadPool()
        self.word_items = {}  # key: (word, subtitle), value: QListWidgetItem

    def add_words(self, words, subtitle, media_id, timestamp):
        for word in words:
            key = (word, subtitle)
            if key not in self.word_items:
                item_text = f"{word} - {subtitle}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, (media_id, timestamp))
                self.word_list.addItem(item)
                self.word_items[key] = item
                # Start image generation in a separate thread
                self.start_image_generation(word, subtitle, item)

    def start_image_generation(self, word, subtitle, item):
        # Implement the logic to start image generation using QThreadPool
        pass  # Replace with actual implementation
