from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDialogButtonBox
)


class MetadataEditDialog(QDialog):
    """Simple dialog to enter or correct episode metadata."""

    def __init__(self, show: str = "", season: int = None, episode: int = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Metadata")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit(show)
        self.season_edit = QLineEdit(str(season) if season is not None else "")
        self.episode_edit = QLineEdit(str(episode) if episode is not None else "")

        form.addRow("Show Title:", self.title_edit)
        form.addRow("Season:", self.season_edit)
        form.addRow("Episode:", self.episode_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        show = self.title_edit.text().strip()
        season_text = self.season_edit.text().strip()
        episode_text = self.episode_edit.text().strip()

        try:
            season = int(season_text) if season_text else None
        except ValueError:
            season = None

        try:
            episode = int(episode_text) if episode_text else None
        except ValueError:
            episode = None

        return show, season, episode
