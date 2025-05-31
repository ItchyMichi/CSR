import logging
import os
import re
import html
import sqlite3
import subprocess
import re
from typing import List, Tuple, Optional, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DatabaseManager")

SURROGATE_RE = re.compile(r'[\ud800-\udfff]')

def remove_surrogates(text: str) -> str:
    """
    Remove UTF-16 surrogate code points, which are invalid in UTF-8.
    """
    if not text:
        return text
    # Substitute the surrogates with empty string or a replacement character
    return SURROGATE_RE.sub('', text)

class DatabaseManager:
    def __init__(self, db_path: str = "study_manager.db", anki=None):
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self.anki = anki  # store the anki object
        self._create_schema()
        self._create_tables()

    def _create_schema(self):
        cur = self._conn.cursor()

        # Drop tables if you want a clean slate (optional):
        # (Uncomment these if you want to forcibly drop them before creating.)
        # cur.execute("DROP TABLE IF EXISTS kanji_linkage")
        # cur.execute("DROP TABLE IF EXISTS kanji_entries")
        # cur.execute("DROP TABLE IF EXISTS compound_forms")
        # cur.execute("DROP TABLE IF EXISTS surface_form_sentences")
        # cur.execute("DROP TABLE IF EXISTS surface_forms")
        # cur.execute("DROP TABLE IF EXISTS dictionary_forms")
        # cur.execute("DROP TABLE IF EXISTS subtitles")
        # cur.execute("DROP TABLE IF EXISTS sentences")
        # cur.execute("DROP TABLE IF EXISTS texts")
        # cur.execute("DROP TABLE IF EXISTS target_content")
        # cur.execute("DROP TABLE IF EXISTS decks")
        # cur.execute("DROP TABLE IF EXISTS media")
        # cur.execute("DROP TABLE IF EXISTS cards")
        # cur.execute("DROP TABLE IF EXISTS card_tags")
        # cur.execute("DROP TABLE IF EXISTS dictionary_info")
        # cur.execute("DROP TABLE IF EXISTS dictionary_words")
        # cur.execute("DROP TABLE IF EXISTS dictionary_definitions")
        # cur.execute("DROP TABLE IF EXISTS study_plans")
        # cur.execute("DROP TABLE IF EXISTS study_plan_words")
        # cur.execute("DROP TABLE IF EXISTS study_plan_step_cards")
        # for i in range(1, 8):
        #     cur.execute(f"DROP TABLE IF EXISTS study_plan_step_{i}")

        # ---------------------------------------------------------
        #  Dictionary info
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS dictionary_info (
            dictionary_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            dictionary_name TEXT UNIQUE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS dictionary_words (
            dictionary_word_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dictionary_id      INTEGER,
            lemma              TEXT,
            pos                TEXT,
            FOREIGN KEY(dictionary_id)
                REFERENCES dictionary_info(dictionary_id)
                ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS dictionary_definitions (
            dictionary_definition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dictionary_word_id       INTEGER,
            definition               TEXT,
            FOREIGN KEY(dictionary_word_id)
                REFERENCES dictionary_words(dictionary_word_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Decks and Media
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS decks (
            deck_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT UNIQUE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS media (
            media_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path      TEXT UNIQUE,
            type           TEXT,
            thumbnail_path TEXT,
            description    TEXT,
            mpv_path       TEXT
        );
        """)

        # ---------------------------------------------------------
        #  Texts, Sentences, Target Content
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS texts (
            text_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            source                    TEXT,
            type                      TEXT,
            comprehension_percentage  REAL DEFAULT 0.0,
            studying                  BOOLEAN DEFAULT 0
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS target_content (
            target_content_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            text_id                   INTEGER,
            priority                  INTEGER,
            comprehension_percentage  REAL,
            text_type                 TEXT,
            FOREIGN KEY(text_id)
                REFERENCES texts(text_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Dictionary Forms / Surface Forms
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS dictionary_forms (
            dict_form_id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_form    TEXT UNIQUE,
            reading      TEXT,
            pos          TEXT,
            frequency    INTEGER DEFAULT 0,
            known        BOOLEAN DEFAULT 0,
            ranking      INTEGER
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS surface_forms (
            surface_form_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dict_form_id    INTEGER,
            surface_form    TEXT,
            reading         TEXT,
            pos             TEXT,
            frequency       INTEGER DEFAULT 0,
            known           BOOLEAN DEFAULT 0,
            ranking         INTEGER,
            kanji_parsed    BOOLEAN DEFAULT 0,
            FOREIGN KEY(dict_form_id)
                REFERENCES dictionary_forms(dict_form_id)
                ON DELETE CASCADE
        );
        """)

        # If upgrading an old DB, ensure the kanji_parsed column exists
        cur.execute("PRAGMA table_info(surface_forms)")
        cols = [row[1] for row in cur.fetchall()]
        if 'kanji_parsed' not in cols:
            cur.execute("ALTER TABLE surface_forms ADD COLUMN kanji_parsed BOOLEAN DEFAULT 0")
            self._conn.commit()

        # Linking table for surface_forms→sentences
        cur.execute("""
        CREATE TABLE IF NOT EXISTS surface_form_sentences (
            surface_form_id INTEGER,
            sentence_id     INTEGER,
            FOREIGN KEY(surface_form_id)
                REFERENCES surface_forms(surface_form_id)
                ON DELETE CASCADE,
            FOREIGN KEY(sentence_id)
                REFERENCES sentences(sentence_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Compound Forms, Kanji
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS compound_forms (
            compound_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            surface_form_id INTEGER,
            compound_text   TEXT,
            frequency       INTEGER DEFAULT 0,
            known           BOOLEAN DEFAULT 0,
            ranking         INTEGER,
            FOREIGN KEY(surface_form_id)
                REFERENCES surface_forms(surface_form_id)
                ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS kanji_entries (
            kanji_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            compound_id INTEGER,
            kanji_char  TEXT,
            frequency   INTEGER DEFAULT 0,
            known       BOOLEAN DEFAULT 0,
            ranking     INTEGER,
            FOREIGN KEY(compound_id)
                REFERENCES compound_forms(compound_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Subtitles, Sentences
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS subtitles (
            sub_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id      INTEGER,
            subtitle_file TEXT UNIQUE,
            language      TEXT,
            format        TEXT,
            FOREIGN KEY(media_id)
                REFERENCES media(media_id)
                ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sentences (
            sentence_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            text_id       INTEGER,
            content       TEXT,
            start_time    REAL,
            end_time      REAL,
            unknown_dictionary_form_count INTEGER DEFAULT 0,
            FOREIGN KEY(text_id)
                REFERENCES texts(text_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Cards, Card Tags
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            card_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id             INTEGER,
            media_id            INTEGER,
            anki_card_id        INTEGER,
            deck_origin         TEXT,
            native_word         TEXT,
            translated_word     TEXT,
            word_audio          TEXT,
            pos                 TEXT,
            native_sentence     TEXT,
            translated_sentence TEXT,
            sentence_audio      TEXT,
            image               TEXT,
            reading             TEXT,
            unobtainable        BOOLEAN DEFAULT 0,
            gated               BOOLEAN DEFAULT 0,
            sentence_id         INTEGER,
            FOREIGN KEY(deck_id) 
                REFERENCES decks(deck_id),
            FOREIGN KEY(media_id)
                REFERENCES media(media_id),
            FOREIGN KEY(sentence_id)
                REFERENCES sentences(sentence_id)
                ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS card_tags (
            card_id INTEGER,
            tag     TEXT,
            FOREIGN KEY(card_id)
                REFERENCES cards(card_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Kanji Linkage
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS kanji_linkage (
            kanji_id        INTEGER,
            surface_form_id INTEGER,
            sentence_id     INTEGER,
            card_id         INTEGER,
            FOREIGN KEY(kanji_id)
                REFERENCES kanji_entries(kanji_id)
                ON DELETE CASCADE,
            FOREIGN KEY(surface_form_id)
                REFERENCES surface_forms(surface_form_id)
                ON DELETE CASCADE,
            FOREIGN KEY(sentence_id)
                REFERENCES sentences(sentence_id)
                ON DELETE CASCADE,
            FOREIGN KEY(card_id)
                REFERENCES cards(card_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Study Plans (and steps)
        # ---------------------------------------------------------
        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plans (
            study_plan_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            order_index     INTEGER,
            text_ids        TEXT,
            card_ids        TEXT,
            current_day     INTEGER DEFAULT 0,
            initial_card_ids TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_step_cards (
            spc_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            study_plan_id INTEGER,
            step_number   INTEGER,
            card_ids      TEXT,
            FOREIGN KEY(study_plan_id)
                REFERENCES study_plans(study_plan_id)
                ON DELETE CASCADE
        );
        """)

        for i in range(1, 8):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS study_plan_step_{i} (
                    step_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    study_plan_id INTEGER,
                    card_sentences   TEXT,
                    text_sentences   TEXT,
                    words_covered    TEXT,
                    text_ids         TEXT,
                    FOREIGN KEY(study_plan_id)
                        REFERENCES study_plans(study_plan_id)
                        ON DELETE CASCADE
                );
            """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_words (
            sp_word_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            study_plan_id INTEGER,
            dict_form_id  INTEGER,
            known         BOOLEAN,
            FOREIGN KEY(study_plan_id)
                REFERENCES study_plans(study_plan_id)
                ON DELETE CASCADE,
            FOREIGN KEY(dict_form_id)
                REFERENCES dictionary_forms(dict_form_id)
                ON DELETE CASCADE
        );
        """)

        # ---------------------------------------------------------
        #  Create Indexes
        # ---------------------------------------------------------
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dictionary_info_name ON dictionary_info(dictionary_name)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dictionary_forms_base_form ON dictionary_forms(base_form)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_texts_source_type ON texts(source, type)")
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_content_time
            ON sentences(text_id, content, start_time, end_time)
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_card_tags_card_tag ON card_tags(card_id, tag)")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_sentences_text_id ON sentences(text_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_texts_type ON texts(type)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_surface_form_sentences_sentence_id ON surface_form_sentences(sentence_id)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_surface_form_sentences_surface_form_id ON surface_form_sentences(surface_form_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_surface_forms_dict_form_id ON surface_forms(dict_form_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dictionary_forms_known ON dictionary_forms(known)")

        self._conn.commit()

    def _create_tables(self):
        # Make sure `sources` (and any other tables) exist:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT NOT NULL
            )
        """)

        # If you have more tables, create them here too:
        # self._conn.execute("""
        #    CREATE TABLE IF NOT EXISTS media (...)
        # """)
        # etc.

        self._conn.commit()

    # Deck management
    def add_deck(self, deck_name: str) -> int:
        cur = self._conn.cursor()
        cur.execute("INSERT OR IGNORE INTO decks (name) VALUES (?)", (deck_name,))
        self._conn.commit()
        cur.execute("SELECT deck_id FROM decks WHERE name = ?", (deck_name,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def file_path_to_mpv_path(self, file_path: str) -> str:
        """
        Converts a normal file system path into MPV's "file://..." URI format.
        Example:
            "C:\\Videos\\myvid.mp4" -> "file:///C:/Videos/myvid.mp4"
        """
        path = file_path.replace("\\", "/")
        if not path.startswith("file://"):
            path = "file://" + path
        return path

    def mpv_path_to_file_path(self, mpv_path: str) -> str:
        """
        Converts an MPV URI ("file://...") back into a normal OS path.
        Will handle removing 'file://' prefix and converting '/' back to
        the local OS separator (on Windows, '\\').
        """
        if mpv_path.startswith("file://"):
            path = mpv_path[7:]
        else:
            path = mpv_path
        return path.replace("/", os.sep)

    def get_next_subtitle(self, media_id: int, current_time: float):
        """
        Return a tuple (start_time, end_time, content) for the next subtitle
        whose start_time is strictly greater than `current_time`.
        If there is no next subtitle, return None.
        """
        logger.info(f"Getting next subtitle for media_id={media_id}, current_time={current_time}")
        cur = self._conn.cursor()
        query = """
            SELECT s.start_time, s.end_time, s.content
              FROM sentences s
              JOIN texts t ON s.text_id = t.text_id
              JOIN subtitles sub ON sub.subtitle_file = t.source
             WHERE sub.media_id = ?
               AND s.start_time > ?
             ORDER BY s.start_time
             LIMIT 1
        """
        cur.execute(query, (media_id, current_time))
        row = cur.fetchone()
        logger.info(f"Next subtitle row: {row}")
        return row if row else None  # row is (start_time, end_time, content)

    def remove_path(self, item_path: str) -> bool:
        """Remove a source, show folder, or episode and cascade all related entries."""
        try:
            import os
            import logging
            logger = logging.getLogger(__name__)
            cur = self._conn.cursor()

            item_path = os.path.normpath(item_path)

            # Check if it's a source
            cur.execute("SELECT source_id FROM sources WHERE folder_path = ?", (item_path,))
            row = cur.fetchone()
            is_source = bool(row)
            source_id = row[0] if row else None

            # Get all media files
            cur.execute("SELECT media_id, file_path FROM media")
            media_rows = cur.fetchall()

            media_ids = []
            path_prefix = item_path + (os.sep if not item_path.endswith(os.sep) else "")

            for mid, file_path in media_rows:
                norm_file = os.path.normpath(file_path)
                if is_source:
                    if norm_file.startswith(path_prefix):
                        media_ids.append(mid)
                else:
                    if norm_file == item_path or norm_file.startswith(path_prefix):
                        media_ids.append(mid)

            if not media_ids and not is_source:
                logger.warning(f"No media found under path: {item_path}")
                return False

            logger.debug(f"Media IDs to delete: {media_ids}")

            text_ids = set()
            for m_id in media_ids:
                cur.execute("SELECT subtitle_file FROM subtitles WHERE media_id = ?", (m_id,))
                for (sub_file,) in cur.fetchall():
                    cur.execute("SELECT text_id FROM texts WHERE source = ? AND type = ?", (sub_file, "video_subtitle"))
                    res = cur.fetchone()
                    if res:
                        text_ids.add(res[0])

            for t_id in text_ids:
                cur.execute("DELETE FROM texts WHERE text_id = ?", (t_id,))
            for m_id in media_ids:
                cur.execute("DELETE FROM media WHERE media_id = ?", (m_id,))

            if is_source:
                cur.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))

            # Clean up orphaned word/kanji forms
            cur.execute(
                "DELETE FROM surface_forms WHERE surface_form_id NOT IN (SELECT surface_form_id FROM surface_form_sentences)")
            cur.execute(
                "DELETE FROM dictionary_forms WHERE dict_form_id NOT IN (SELECT dict_form_id FROM surface_forms)")

            self._conn.commit()
            logger.info(f"Deleted {len(media_ids)} media, {len(text_ids)} texts, path={item_path}")
            return True

        except Exception as e:
            logger.error("Failed to remove path", exc_info=True)
            return False

    def get_subtitle_for_time(self, media_id: int, current_time: float):
        """
        Return (start_time, end_time, content) if there's a subtitle that covers
        current_time, i.e. start_time <= current_time < end_time.
        If none, return None.
        """
        cur = self._conn.cursor()
        query = """
            SELECT s.start_time, s.end_time, s.content
              FROM sentences s
              JOIN texts t ON s.text_id = t.text_id
              JOIN subtitles sub ON sub.subtitle_file = t.source
             WHERE sub.media_id = ?
               AND s.start_time <= ?
               AND s.end_time > ?
             LIMIT 1
        """
        cur.execute(query, (media_id, current_time, current_time))
        row = cur.fetchone()
        return row if row else None

    def get_previous_subtitle(self, media_id: int, current_time: float):
        """
        Return (start_time, end_time, content) for the subtitle whose start_time
        is right before current_time, i.e. the largest start_time that is still < current_time.
        If none found, return None.
        """
        cur = self._conn.cursor()
        query = """
            SELECT s.start_time, s.end_time, s.content
              FROM sentences s
              JOIN texts t ON s.text_id = t.text_id
              JOIN subtitles sub ON sub.subtitle_file = t.source
             WHERE sub.media_id = ?
               AND s.start_time < ?
             ORDER BY s.start_time DESC
             LIMIT 1
        """
        cur.execute(query, (media_id, current_time))
        row = cur.fetchone()
        logger.info(f"Previous subtitle row: {row}")
        return row if row else None

    def remove_surface_form_sentence_links(self, sentence_id: int):
        """
        Remove all links in surface_form_sentences referencing the given sentence_id.
        """
        cur = self._conn.cursor()
        # Just delete the rows in the linking table for this sentence
        cur.execute("""
            DELETE FROM surface_form_sentences
             WHERE sentence_id = ?
        """, (sentence_id,))
        self._conn.commit()

    def remove_sentences_for_text(self, text_id: int):
        """
        Delete all sentences (rows) in the 'sentences' table for a given text_id.
        """
        cur = self._conn.cursor()
        cur.execute("""
            DELETE FROM sentences
             WHERE text_id = ?
        """, (text_id,))
        self._conn.commit()

    def insert_sentence(self, text_id: int, content: str, start_time: float, end_time: float) -> int:
        """
        Insert a new sentence row and return its sentence_id (primary key).
        """
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO sentences (text_id, content, start_time, end_time)
            VALUES (?, ?, ?, ?)
        """, (text_id, content, start_time, end_time))
        self._conn.commit()

        # The last inserted row ID is our new sentence_id
        return cur.lastrowid

    def set_text_studying(self, text_id: int, studying: bool):
        """
        Mark a specific text_id as studying (True/False).
        """
        cur = self._conn.cursor()
        cur.execute("UPDATE texts SET studying = ? WHERE text_id = ?", (1 if studying else 0, text_id))
        self._conn.commit()

    def add_source_folder(self, folder_path: str) -> int:
        # Insert into a table named "sources" or something:
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT UNIQUE
            )
        """)
        self._conn.commit()

        cur.execute("INSERT OR IGNORE INTO sources (folder_path) VALUES (?)", (folder_path,))
        self._conn.commit()

        # Return the ID
        cur.execute("SELECT source_id FROM sources WHERE folder_path = ?", (folder_path,))
        row = cur.fetchone()
        return row[0] if row else None

    def get_subdirectories_for_source(self, source_id: int) -> list:
        # If you do not actually store subdirs, just return an empty list
        return []

    def subtitle_already_exists(self, subtitle_file: str) -> bool:
        """
        Return True if the given subtitle_file is already in the 'subtitles' table,
        False otherwise.
        """
        cur = self._conn.cursor()
        cur.execute("SELECT sub_id FROM subtitles WHERE subtitle_file = ?", (subtitle_file,))
        row = cur.fetchone()
        return row is not None

    def add_subtitle(self, media_id: int, subtitle_file: str, language: str = "unknown", format: str = "srt") -> int:
        """
        Inserts a subtitle file record associated with a media file.
        Returns the subtitle record ID.
        """
        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO subtitles (media_id, subtitle_file, language, format)
            VALUES (?, ?, ?, ?)
        """, (media_id, subtitle_file, language, format))
        self._conn.commit()
        cur.execute("SELECT sub_id FROM subtitles WHERE subtitle_file = ?", (subtitle_file,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def get_all_sources(self) -> list:
        """
        Return a list of dicts like [{"source_id": 1, "root_path": "/some/folder"}].
        """
        logger.info("Retrieving all sources from the database.")
        cur = self._conn.cursor()
        logger.info("Executing query to fetch all sources.")
        cur.execute("SELECT source_id, folder_path FROM sources")
        logger.info("Fetching all rows.")
        rows = cur.fetchall()
        logger.info(f"Found {len(rows)} sources.")
        result = []
        for r in rows:
            result.append({"source_id": r[0], "root_path": r[1]})
            logger.info(f"Source ID: {r[0]}, Root Path: {r[1]}")
        return result


    def index_subtitle_cues(self, media_id: int, subtitle_file: str, cues: List[Dict]):
        """
        Index each subtitle cue from a subtitle file.
        This method treats the subtitle file as a text source (with type 'video_subtitle')
        and inserts each cue into the 'sentences' table with start_time and end_time.
        """
        text_id = self.add_text_source(source_path=subtitle_file, text_type="video_subtitle")
        cur = self._conn.cursor()
        for cue in cues:
            cur.execute("""
                INSERT INTO sentences (text_id, content, start_time, end_time)
                VALUES (?, ?, ?, ?)
            """, (text_id, cue.get("text", "").strip(), cue.get("start", 0.0), cue.get("end", 0.0)))
        self._conn.commit()

    def get_or_create_deck(self, deck_name: str) -> int:
        deck_id = self.get_deck_id_by_name(deck_name)
        if deck_id is None:
            deck_id = self.add_deck(deck_name)
        return deck_id

    def get_deck_id_by_name(self, deck_name: str) -> Optional[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT deck_id FROM decks WHERE name = ?", (deck_name,))
        row = cur.fetchone()
        return row[0] if row else None

    def ensure_Words_deck_exists(self) -> int:
        return self.get_or_create_deck("Words")

    def get_252_cards_from_Words(self) -> List[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT card_id, sentence_id FROM cards WHERE deck_id = 1 AND unobtainable = 0")
        candidates = cur.fetchall()

        if not candidates:
            return []

        card_freq_map = []
        for card_id, sentence_id in candidates:
            freq_score = self._calculate_card_frequency_score(sentence_id)
            card_freq_map.append((card_id, freq_score))

        card_freq_map.sort(key=lambda x: x[1], reverse=True)
        logging.info(f"Selected {len(card_freq_map)} cards from Words deck.")
        selected = [c[0] for c in card_freq_map[:252]]
        return selected

    def find_top_36_unobtainable_one_unknown(self) -> List[int]:
        cur = self._conn.cursor()
        query = """
        SELECT c.card_id
        FROM cards c
        JOIN sentences s ON c.sentence_id = s.sentence_id
        WHERE c.unobtainable = 1
          AND s.unknown_dictionary_form_count = 1
        ORDER BY c.card_id
        LIMIT 36
        """
        cur.execute(query)
        rows = cur.fetchall()
        if not rows:
            logger.info("No unobtainable cards found with exactly one unknown dictionary form.")
            return []
        card_ids = [row[0] for row in rows]
        return card_ids

    def move_cards_to_deck(self, deck_name: str, card_ids: List[int]):
        if not card_ids:
            logger.info("No card_ids provided to move.")
            return

        if not self.anki:
            logger.warning("No anki instance found, cannot move cards.")
            return

        logger.info(f"Attempting to move {len(card_ids)} local cards to '{deck_name}'. Card IDs: {card_ids}")
        deck_id = self.get_deck_id_by_name(deck_name)
        if deck_id is None:
            logger.info(f"'{deck_name}' not found in local DB, creating it now.")
            deck_id = self.get_or_create_deck(deck_name)

        anki_decks = self.anki.get_decks()
        if deck_name not in anki_decks:
            logger.warning(f"'{deck_name}' deck not found in Anki. Attempting to create it.")
            res = self.anki.invoke("createDeck", deck=deck_name)
            if res is None:
                logger.error(f"Failed to create '{deck_name}' in Anki.")
            else:
                logger.info(f"'{deck_name}' created in Anki.")

        placeholders = ",".join("?" for _ in card_ids)
        query = f"SELECT card_id, anki_card_id FROM cards WHERE card_id IN ({placeholders})"
        cur = self._conn.cursor()
        cur.execute(query, card_ids)
        card_map = cur.fetchall()
        anki_card_ids = [row[1] for row in card_map if row[1] is not None]
        if not anki_card_ids:
            logger.warning("No anki_card_ids found for the given card_ids. Cannot move them in Anki.")
            return

        logger.info(f"Invoking AnkiConnect to change deck of {anki_card_ids} to '{deck_name}'.")
        change_result = self.anki.change_deck(anki_card_ids, deck_name)
        if change_result is None:
            logger.warning("AnkiConnect returned None from 'change_deck' (possible success).")

        logger.info(f"Updating local DB to set deck_id={deck_id} for these cards.")
        cur.execute(f"UPDATE cards SET deck_id = ? WHERE card_id IN ({placeholders})", [deck_id] + card_ids)
        self._conn.commit()
        logger.info(f"Local DB updated: {len(card_ids)} cards moved to deck_id={deck_id} ({deck_name}).")



    def _calculate_card_frequency_score(self, sentence_id: int) -> int:
        cur = self._conn.cursor()
        cur.execute("""
        SELECT df.frequency
        FROM dictionary_forms df
        JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
        JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
        WHERE sfs.sentence_id = ?
        """, (sentence_id,))
        freqs = [row[0] for row in cur.fetchall()]
        return sum(freqs) if freqs else 0

    def update_dictionary_form_rankings(self):
        """
        Re-rank each dictionary_form based on the sum of surface_form.frequency
        within all sentences belonging to texts where studying=1.

        The bigger the total frequency, the higher (better) the rank => rank=1 means highest frequency.
        """
        cur = self._conn.cursor()

        # 1) Build an in-memory table: dict_form_id -> sum_of_freq_in_studied_texts
        # We do a left join so that dictionary_forms with *zero* appearances in studying texts
        # still appear with total=0 (and get the worst rank).
        # For dictionary forms that do appear in studied texts, we sum up all surface_forms.frequency.
        # (We assume you increment surface_forms.frequency as you parse lines.)
        query = """
        WITH freq AS (
          SELECT
            df.dict_form_id,
            IFNULL(SUM(sf.frequency), 0) AS total_freq
          FROM dictionary_forms df
          LEFT JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
          LEFT JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
          LEFT JOIN sentences se ON sfs.sentence_id = se.sentence_id
          LEFT JOIN texts t ON se.text_id = t.text_id
          WHERE t.studying = 1
             OR t.studying IS NULL  -- If you only want the ones with studying=1, remove this line
          GROUP BY df.dict_form_id
        )
        SELECT dict_form_id, total_freq
        FROM freq
        ORDER BY total_freq DESC
        """

        cur.execute(query)
        rows = cur.fetchall()

        # 2) Now 'rows' is a list of (dict_form_id, total_freq), sorted descending
        # We'll assign rank=1 to the biggest total_freq, rank=2 to second, etc.
        rank = 1
        for (df_id, total_freq) in rows:
            cur.execute("UPDATE dictionary_forms SET ranking = ? WHERE dict_form_id = ?", (rank, df_id))
            rank += 1

        self._conn.commit()

    def get_text_comprehension(self, text_id: int) -> Optional[float]:
        """
        Return the 'comprehension_percentage' for the specified text_id.
        If there's no matching row or the percentage is NULL, return None.
        """
        cur = self._conn.cursor()
        cur.execute("SELECT comprehension_percentage FROM texts WHERE text_id = ?", (text_id,))
        row = cur.fetchone()
        if row is None:
            # No matching text_id at all
            return None
        logger.info(f"Comprehension percentage for text_id={text_id}: {row[0]}")
        return row[0]  # May be float or None (if the column is NULL)

    def get_local_card_ids_for_anki_ids(self, anki_card_ids: List[int]) -> List[int]:
        if not anki_card_ids:
            return []
        logger.info(f"Fetching local card_ids for {len(anki_card_ids)} anki_card_ids.")
        placeholders = ",".join("?" for _ in anki_card_ids)
        query = f"SELECT card_id FROM cards WHERE anki_card_id IN ({placeholders})"
        cur = self._conn.cursor()
        cur.execute(query, anki_card_ids)
        rows = cur.fetchall()
        local_ids = [row[0] for row in rows if row[0] is not None]
        return local_ids

    def get_anki_import_decks(self) -> List[str]:
        logger.info("Retrieving anki_import decks from 'texts' table.")
        cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT source FROM texts WHERE type='anki_import' AND source <> ''")
        rows = cur.fetchall()
        decks = [row[0] for row in rows if row[0]]
        logger.info(f"Found {len(decks)} anki_import decks: {decks}")
        return decks

    def get_cards_by_deck_origin(self, deck_origin: str) -> List[dict]:
        logger.info(f"Retrieving cards for deck_origin='{deck_origin}'")
        cur = self._conn.cursor()
        query = """
            SELECT card_id,
                   native_word,
                   translated_word,
                   pos,
                   reading,
                   native_sentence,
                   translated_sentence,
                   word_audio,
                   sentence_audio,
                   image
              FROM cards
             WHERE deck_origin = ?
             ORDER BY card_id
        """
        cur.execute(query, (deck_origin,))
        rows = cur.fetchall()
        result = []
        for row in rows:
            result.append({
                "card_id": row[0],
                "native_word": row[1] or "",
                "translated_word": row[2] or "",
                "pos": row[3] or "",
                "reading": row[4] or "",
                "native_sentence": row[5] or "",
                "translated_sentence": row[6] or "",
                "word_audio": row[7] or "",
                "sentence_audio": row[8] or "",
                "image": row[9] or ""
            })
        logger.info(f"Found {len(result)} cards for deck_origin='{deck_origin}'")
        return result

    def get_anki_card_ids_for_local_cards(self, local_card_ids: List[int]) -> List[int]:
        logging.info(f"Fetching anki_card_ids for {len(local_card_ids)} local card_ids.")
        if not local_card_ids:
            return []
        placeholders = ",".join("?" for _ in local_card_ids)
        query = f"SELECT anki_card_id FROM cards WHERE card_id IN ({placeholders})"
        cur = self._conn.cursor()
        cur.execute(query, local_card_ids)
        rows = cur.fetchall()
        anki_ids = [r[0] for r in rows if r[0]]
        return anki_ids

    def update_card_audio(self, card_id: int, which: str, new_value: str):
        if which.lower() == "word":
            col_name = "word_audio"
        else:
            col_name = "sentence_audio"

        query = f"UPDATE cards SET {col_name} = ? WHERE card_id = ?"
        cur = self._conn.cursor()
        cur.execute(query, (new_value, card_id))
        self._conn.commit()
        logging.info(f"Local DB: updated {col_name} for card_id={card_id} to '{new_value}'")

    def update_card_image(self, card_id: int, new_image_html: str):
        query = "UPDATE cards SET image = ? WHERE card_id = ?"
        cur = self._conn.cursor()
        cur.execute(query, (new_image_html, card_id))
        self._conn.commit()
        logging.info(f"Local DB: updated image for card_id={card_id} to '{new_image_html}'")

    def get_anki_card_id(self, local_card_id: int) -> Optional[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT anki_card_id FROM cards WHERE card_id = ?", (local_card_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def update_anki_note_field(self, anki_card_id: int, anki_field_name: str, new_value: str):
        logging.info(f"Fetching note ID for anki_card_id={anki_card_id}")
        resp = self.anki.invoke("cardsInfo", cards=[anki_card_id])
        logging.info(f"AnkiConnect response for cardsInfo: {resp}")

        if not isinstance(resp, list):
            logging.error(f"cardsInfo returned something else: {resp}")
            return

        if not resp:
            logging.error("cardsInfo returned an empty list.")
            return

        first_card = resp[0]
        logging.info(f"First card info: {first_card}")
        note_id = first_card.get("note")
        if not note_id:
            logging.error("No 'note' key found in the card info.")
            return

        logging.info(f"Will update note {note_id}, field '{anki_field_name}' => '{new_value}'")

        update_req = {
            "action": "updateNoteFields",
            "version": 6,
            "params": {
                "note": {
                    "id": note_id,
                    "fields": {
                        anki_field_name: new_value
                    }
                }
            }
        }

        update_response = self.anki.invoke_raw(update_req)
        if not update_response or update_response.get("error"):
            logging.error(f"Failed to update note field: {update_response}")
        else:
            logging.info(f"Successfully updated note {note_id}, field='{anki_field_name}' => {new_value}")

    def get_due_review_cards(self) -> List[int]:
        logger.info("Fetching *currently due* or overdue cards from 'Study' deck.")
        if not self.anki:
            logger.info("No anki instance found in DatabaseManager.")
            return []
        query = "deck:'Study' prop:due<=1"
        logger.info(f"Querying anki for due cards with: {query}")
        due_cards = self.anki.find_cards(query)

        if due_cards is None:
            logger.info("No cards found for due review or error in query.")
            due_cards = []
        else:
            logger.info(f"Found {len(due_cards)} due review cards.")
        return due_cards

    def get_final_text_list(self, study_plan_id: int) -> List[int]:
        all_texts = set()
        cur = self._conn.cursor()
        for day in range(1, 8):
            table_name = f"study_plan_step_{day}"
            cur.execute(f"SELECT text_ids FROM {table_name} WHERE study_plan_id = ?", (study_plan_id,))
            row = cur.fetchone()
            if row and row[0]:
                day_text_ids = [int(x) for x in row[0].split(';') if x.strip()]
                for t_id in day_text_ids:
                    all_texts.add(t_id)
        return list(all_texts)

    def create_new_study_plan(self, card_ids: List[int]) -> int:
        card_ids_str = ";".join(str(c) for c in card_ids)
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO study_plans (order_index, text_ids, card_ids, current_day, initial_card_ids) VALUES (?, ?, ?, ?, ?)",
            (1, "", card_ids_str, 0, card_ids_str))
        self._conn.commit()
        return cur.lastrowid

    def get_cards_for_study_plan_day(self, study_plan_id: int, step_number: int) -> List[int]:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT card_ids
              FROM study_plan_step_cards
             WHERE study_plan_id = ?
               AND step_number = ?
        """, (study_plan_id, step_number))
        row = cur.fetchone()
        if not row or not row[0]:
            return []
        return [int(x) for x in row[0].split(';') if x.strip()]

    def clear_study_plan(self):
        cur = self._conn.cursor()
        cur.execute("DELETE FROM study_plans")
        self._conn.commit()

    def get_current_study_plan(self) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT study_plan_id, current_day, initial_card_ids, card_ids FROM study_plans LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        return {
            "study_plan_id": row[0],
            "current_day": row[1],
            "initial_card_ids": row[2],
            "card_ids": row[3]
        }

    def store_day_card_ids(self, study_plan_id: int, step_number: int, day_cards: List[int]) -> None:
        card_ids_str = ";".join(str(c) for c in day_cards)
        cur = self._conn.cursor()
        cur.execute("""
            SELECT spc_id
              FROM study_plan_step_cards
             WHERE study_plan_id = ?
               AND step_number = ?
        """, (study_plan_id, step_number))
        existing = cur.fetchone()

        if existing:
            spc_id = existing[0]
            cur.execute("""
                UPDATE study_plan_step_cards
                   SET card_ids = ?
                 WHERE spc_id = ?
            """, (card_ids_str, spc_id))
        else:
            cur.execute("""
                INSERT INTO study_plan_step_cards (study_plan_id, step_number, card_ids)
                     VALUES (?, ?, ?)
            """, (study_plan_id, step_number, card_ids_str))

        self._conn.commit()

    def update_study_plan_day(self, study_plan_id: int, current_day: int):
        cur = self._conn.cursor()
        cur.execute("UPDATE study_plans SET current_day = ? WHERE study_plan_id = ?", (current_day, study_plan_id))
        self._conn.commit()

    def move_cards_to_study(self, card_ids: List[int]):
        if not card_ids:
            logger.info("No card_ids provided to move to Study.")
            return

        if not self.anki:
            logger.warning("No anki instance found, cannot move cards to Study.")
            return

        logger.info(f"Attempting to move {len(card_ids)} local cards to 'Study'. Card IDs: {card_ids}")
        cur = self._conn.cursor()
        q_marks = ",".join("?" for _ in card_ids)
        cur.execute(f"SELECT card_id, anki_card_id FROM cards WHERE card_id IN ({q_marks})", card_ids)
        card_map = cur.fetchall()
        anki_card_ids = [row[1] for row in card_map if row[1] is not None]
        if not anki_card_ids:
            logger.warning("No anki_card_ids found for the given card_ids. Cannot move them in Anki.")
            return

        logger.info(f"Anki card IDs to move: {anki_card_ids}")
        Study_id = self.get_deck_id_by_name("Study")
        if Study_id is None:
            logger.info("'Study' not found in local DB, creating it now.")
            Study_id = self.ensure_Study_exists()
        else:
            logger.info(f"Study found with deck_id={Study_id} in local DB.")

        anki_decks = self.anki.get_decks()
        if "Study" not in anki_decks:
            logger.warning("'Study' deck not found in Anki. Attempting to create it.")
            res = self.anki.invoke("createDeck", deck="Study")
            if res is None:
                logger.error("Failed to create 'Study' in Anki.")
            else:
                logger.info("'Study' created in Anki.")

        logger.info("Invoking AnkiConnect to change deck of the selected anki_card_ids to 'Study'.")
        change_result = self.anki.change_deck(anki_card_ids, "Study")
        if change_result is None:
            logger.warning("AnkiConnect returned None from 'change_deck' (possible success).")
        else:
            logger.info("changeDeck action via AnkiConnect did not return None—likely success.")

        logger.info("Updating local DB to set deck_id=2 for these cards.")
        cur.execute(f"UPDATE cards SET deck_id = 2 WHERE card_id IN ({q_marks})", card_ids)
        self._conn.commit()
        logger.info(f"Local DB updated: {len(card_ids)} cards moved to deck_id=2 (Study).")

    def simulate_review_cards(self, local_card_ids: List[int], ease_mapping: Optional[Dict[int, int]] = None) -> bool:
        if not local_card_ids:
            logger.info("No local card IDs provided to simulate review.")
            return False

        if not self.anki:
            logger.warning("No anki instance found, cannot simulate review in Anki.")
            return False

        cur = self._conn.cursor()
        placeholders = ",".join("?" for _ in local_card_ids)
        query = f"SELECT card_id, anki_card_id FROM cards WHERE card_id IN ({placeholders})"
        cur.execute(query, local_card_ids)
        rows = cur.fetchall()

        if not rows:
            logger.info("No matching anki_card_ids found for the given local card IDs.")
            return False

        answers = []
        default_ease = 3
        for local_id, anki_id in rows:
            if not anki_id:
                logger.warning(f"No anki_card_id for local card_id={local_id}, skipping.")
                continue
            if ease_mapping and local_id in ease_mapping:
                ease_value = ease_mapping[local_id]
            else:
                ease_value = default_ease
            answers.append({"cardId": anki_id, "ease": ease_value})

        if not answers:
            logger.info("No valid anki_card_ids to simulate review.")
            return False

        logger.info(f"Simulating review for {len(answers)} cards: {answers}")
        result = self.anki.invoke("answerCards", answers=answers)
        if result is None:
            logger.error("answerCards invocation failed.")
            return False

        logger.info("answerCards invocation succeeded.")
        return True

    def get_all_text_import_ids(self) -> List[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT text_id FROM texts WHERE type='text_import'")
        return [r[0] for r in cur.fetchall()]

    def get_all_challenge_text_ids(self) -> List[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT text_id FROM texts WHERE type='challenge'")
        return [r[0] for r in cur.fetchall()]

    def append_study_plan_tables(self):
        cur = self._conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plans (
            study_plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_index INTEGER,
            text_ids TEXT,
            card_ids TEXT,
            current_day INTEGER DEFAULT 0,
            initial_card_ids TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_step_1 (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_plan_id INTEGER,
            card_sentences TEXT,
            text_sentences TEXT,
            words_covered TEXT,
            text_ids TEXT,
            FOREIGN KEY(study_plan_id) REFERENCES study_plans(study_plan_id)
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_step_2 (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_plan_id INTEGER,
            card_sentences TEXT,
            text_sentences TEXT,
            words_covered TEXT,
            text_ids TEXT,
            FOREIGN KEY(study_plan_id) REFERENCES study_plans(study_plan_id)
        );
        """)
        for i in range(3, 8):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS study_plan_step_{i} (
                    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    study_plan_id INTEGER,
                    card_sentences TEXT,
                    text_sentences TEXT,
                    words_covered TEXT,
                    text_ids TEXT,
                    FOREIGN KEY(study_plan_id) REFERENCES study_plans(study_plan_id)
                );
            """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_day_cards (
            spdc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_plan_id INTEGER,
            day_num INTEGER,
            card_ids TEXT,
            FOREIGN KEY(study_plan_id) REFERENCES study_plans(study_plan_id)
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_words (
            sp_word_id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_plan_id INTEGER,
            dict_form_id INTEGER,
            known BOOLEAN,
            FOREIGN KEY(study_plan_id) REFERENCES study_plans(study_plan_id),
            FOREIGN KEY(dict_form_id) REFERENCES dictionary_forms(dict_form_id)
        );
        """)
        self._conn.commit()
        logging.info("Appended study plan tables (including 'study_plan_day_cards') to the existing database schema.")

    def update_media_metadata(self, media_id: int,
                              thumbnail_path: Optional[str] = None,
                              description: Optional[str] = None):
        """
        Update 'thumbnail_path' and/or 'description' for a given media row.
        If you pass None, it won't overwrite existing values.
        """
        # First, fetch existing row so we only overwrite columns you explicitly provide.
        cur = self._conn.cursor()
        cur.execute("SELECT thumbnail_path, description FROM media WHERE media_id = ?", (media_id,))
        row = cur.fetchone()
        if not row:
            # media_id doesn't exist
            return

        current_thumb, current_desc = row[0], row[1]

        # Use the old value if we got None for the param
        new_thumb = thumbnail_path if thumbnail_path is not None else current_thumb
        new_desc = description if description is not None else current_desc

        cur.execute("""
            UPDATE media
               SET thumbnail_path = ?,
                   description = ?
             WHERE media_id = ?
        """, (new_thumb, new_desc, media_id))
        self._conn.commit()

    def get_cards_by_local_deck_name(self, deck_name: str) -> list:
        """
        Return a list of dicts for all cards whose 'deck_id' matches the
        named deck in the 'decks' table (e.g. 'Words', 'Study').
        """
        # 1) Look up deck_id by name
        deck_id = self.get_deck_id_by_name(deck_name)
        if deck_id is None:
            logging.info(f"No local deck found named '{deck_name}'")
            return []

        # 2) Fetch cards with that deck_id
        cur = self._conn.cursor()
        cur.execute("""
          SELECT card_id,
                 native_word,
                 translated_word,
                 pos,
                 reading,
                 native_sentence,
                 translated_sentence,
                 word_audio,
                 sentence_audio,
                 image
            FROM cards
           WHERE deck_id = ?
           ORDER BY card_id
        """, (deck_id,))
        rows = cur.fetchall()

        result = []
        for r in rows:
            result.append({
                "card_id": r[0],
                "native_word": r[1] or "",
                "translated_word": r[2] or "",
                "pos": r[3] or "",
                "reading": r[4] or "",
                "native_sentence": r[5] or "",
                "translated_sentence": r[6] or "",
                "word_audio": r[7] or "",
                "sentence_audio": r[8] or "",
                "image": r[9] or ""
            })
        return result

    def get_media_info(self, media_id: int) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT file_path, type, thumbnail_path, description, mpv_path
              FROM media
             WHERE media_id = ?
        """, (media_id,))
        row = cur.fetchone()
        if not row:
            return None

        return {
            "file_path": row[0],
            "type": row[1],
            "thumbnail_path": row[2],
            "description": row[3],
            "mpv_path": row[4],
        }

    def get_dict_form_info(self, dict_form_id: int) -> Optional[dict]:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT base_form, pos, reading, known
              FROM dictionary_forms
             WHERE dict_form_id = ?
        """, (dict_form_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "base_form": row[0] or "",
            "pos": row[1] or "",
            "reading": row[2] or "",
            "known": bool(row[3]),
        }

    def get_unknown_forms_from_cards(self, card_ids: List[int]) -> List[int]:
        unknown_set = set()
        for c_id in card_ids:
            uf = self.get_unknown_dict_forms_from_card(c_id)
            for f in uf:
                unknown_set.add(f)
        return list(unknown_set)

    def get_gated_dict_forms(self) -> List[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT card_id FROM cards WHERE gated = 1")
        gated_cards = [r[0] for r in cur.fetchall()]
        return self.get_unknown_forms_from_cards(gated_cards)

    def get_forms_covered_by_text(self, text_id: int) -> set:
        cur = self._conn.cursor()
        cur.execute("""
        SELECT DISTINCT df.dict_form_id
        FROM dictionary_forms df
        JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
        JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
        JOIN sentences s ON s.sentence_id = sfs.sentence_id
        WHERE s.text_id = ?;
        """, (text_id,))
        return {row[0] for row in cur.fetchall()}

    def greedy_set_cover(self, forms: List[int], text_ids: List[int], text_type: str, limit: Optional[int] = None) -> List[int]:
        uncovered = set(forms)
        chosen_texts = []
        coverage_map = {}
        for t_id in text_ids:
            coverage_map[t_id] = self.get_forms_covered_by_text(t_id)

        while uncovered and (limit is None or len(chosen_texts) < limit):
            best_text = None
            best_cover_count = 0
            for t_id in text_ids:
                if t_id in chosen_texts:
                    continue
                cover = coverage_map[t_id] & uncovered
                if len(cover) > best_cover_count:
                    best_cover_count = len(cover)
                    best_text = t_id
            if best_text is None:
                break
            chosen_texts.append(best_text)
            uncovered -= coverage_map[best_text]
        return chosen_texts

    def get_card_sentences_as_str(self, card_ids: List[int]) -> str:
        rows = self.get_sentences_for_cards(";".join(str(c) for c in card_ids))
        sentences = [r[1] for r in rows]
        return ";".join(sentences)

    def get_text_sentences_as_str(self, text_ids: List[int]) -> str:
        sentence_list = []
        for t_id in text_ids:
            srows = self.get_sentences_for_text(t_id)
            for sr in srows:
                sentence_list.append(sr[1])
        return ";".join(sentence_list)

    def get_words_covered_str(self, forms: List[int]) -> str:
        if not forms:
            return ""
        cur = self._conn.cursor()
        placeholders = ",".join("?" for _ in forms)
        cur.execute(f"SELECT base_form FROM dictionary_forms WHERE dict_form_id IN ({placeholders})", forms)
        words = [row[0] for row in cur.fetchall()]
        return ";".join(words)

    def ensure_Study_exists(self) -> int:
        return self.get_or_create_deck("Study")

    def add_media(self, file_path: str, media_type: str) -> int:
        """
        Inserts a media record. Also auto-generates an mpv_path for the newly inserted media.
        Returns the media_id of the inserted row.
        """
        mpv_path = self.file_path_to_mpv_path(file_path)
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO media (file_path, type, mpv_path) VALUES (?, ?, ?)",
            (file_path, media_type, mpv_path)
        )
        self._conn.commit()
        cur.execute("SELECT media_id FROM media WHERE file_path = ?", (file_path,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def add_card(self, deck_id: int, media_id: Optional[int] = None,
                 anki_card_id: Optional[int] = None, deck_origin: Optional[str] = None,
                 native_word: Optional[str] = None, translated_word: Optional[str] = None,
                 word_audio: Optional[str] = None, pos: Optional[str] = None,
                 native_sentence: Optional[str] = None, translated_sentence: Optional[str] = None,
                 sentence_audio: Optional[str] = None, image: Optional[str] = None,
                 reading: Optional[str] = None, sentence_id: Optional[int] = None) -> int:

        cur = self._conn.cursor()
        cur.execute("""
        INSERT INTO cards (deck_id, media_id, anki_card_id, deck_origin, native_word, translated_word,
                           word_audio, pos, native_sentence, translated_sentence, sentence_audio, image, reading, sentence_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (deck_id, media_id, anki_card_id, deck_origin, native_word, translated_word,
              word_audio, pos, native_sentence, translated_sentence, sentence_audio, image, reading, sentence_id))
        self._conn.commit()
        return cur.lastrowid

    def set_card_anki_id(self, card_id: int, anki_card_id: int):
        cur = self._conn.cursor()
        cur.execute("UPDATE cards SET anki_card_id = ? WHERE card_id = ?", (anki_card_id, card_id))
        self._conn.commit()

    def update_card_tags(self, card_id: int, tags: List[str]):
        cur = self._conn.cursor()
        for t in tags:
            cur.execute("INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)", (card_id, t))
        self._conn.commit()

    def set_card_gated(self, card_id: int, gated: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE cards SET gated = ? WHERE card_id = ?", (1 if gated else 0, card_id))
        self._conn.commit()

    def add_text_source(self, source_path: str, text_type: str) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT text_id FROM texts WHERE source = ? AND type = ?", (source_path, text_type))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO texts (source, type) VALUES (?, ?)", (source_path, text_type))
        self._conn.commit()
        return cur.lastrowid

    def filter_cards_by_coverage(self, candidate_card_ids: List[int], chosen_text_ids: List[int]) -> List[int]:
        selected_cards = []
        for card_id in candidate_card_ids:
            unknown_forms = self.get_unknown_dict_forms_from_card(card_id)
            if not unknown_forms:
                selected_cards.append(card_id)
            else:
                covered = True
                for df_id in unknown_forms:
                    if not self.dict_form_covered_by_texts(df_id, chosen_text_ids):
                        covered = False
                        break
                if covered:
                    selected_cards.append(card_id)
                    self.set_card_unobtainable(card_id, False)
                else:
                    self.set_card_unobtainable(card_id, True)
        return selected_cards

    def get_unknown_dict_forms_from_card(self, card_id: int) -> List[int]:
        cur = self._conn.cursor()
        cur.execute("SELECT sentence_id FROM cards WHERE card_id = ?", (card_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return []
        sentence_id = row[0]
        cur.execute("""
            SELECT DISTINCT df.dict_form_id
            FROM dictionary_forms df
            JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
            JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
            WHERE sfs.sentence_id = ?
              AND df.known = 0;
        """, (sentence_id,))
        unknown_form_ids = [r[0] for r in cur.fetchall()]
        return unknown_form_ids

    def dict_form_covered_by_texts(self, dict_form_id: int, chosen_text_ids: List[int]) -> bool:
        if not chosen_text_ids:
            return False
        cur = self._conn.cursor()
        placeholders = ",".join("?" for _ in chosen_text_ids)
        query = f"""
            SELECT COUNT(*) 
            FROM dictionary_forms df
            JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
            JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
            JOIN sentences s ON sfs.sentence_id = s.sentence_id
            WHERE df.dict_form_id = ?
              AND s.text_id IN ({placeholders});
        """
        params = [dict_form_id] + chosen_text_ids
        cur.execute(query, params)
        count = cur.fetchone()[0]
        return count > 0

    def set_card_unobtainable(self, card_id: int, unobtainable: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE cards SET unobtainable = ? WHERE card_id = ?", (1 if unobtainable else 0, card_id))
        self._conn.commit()

    def add_sentence_if_not_exist(self, text_id: int, sentence_str: str) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT sentence_id FROM sentences WHERE text_id = ? AND content = ?", (text_id, sentence_str))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO sentences (text_id, content) VALUES (?, ?)", (text_id, sentence_str))
        self._conn.commit()
        return cur.lastrowid

    def get_random_sentence(self):
        cur = self._conn.cursor()
        cur.execute("""
            SELECT s.sentence_id, s.content
            FROM sentences s
            JOIN texts t ON s.text_id = t.text_id
            WHERE t.type = 'anki_import'
            ORDER BY RANDOM() LIMIT 1;
        """)
        row = cur.fetchone()
        return row if row else None

    def get_surface_forms_for_text_content(self, text: str):
        """
        Return a list of (surface_form_id, surface_form, dict_form_id, base_form, known)
        for any sentence whose 'content' matches 'text'.
        """
        # (we'll still keep this, but see DISTINCT version below)
        cur = self._conn.cursor()
        query = """
        SELECT DISTINCT
               sf.surface_form_id,
               sf.surface_form,
               df.dict_form_id,
               df.base_form,
               df.known
          FROM surface_forms sf
          JOIN dictionary_forms df        ON sf.dict_form_id = df.dict_form_id
          JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
          JOIN sentences s ON sfs.sentence_id = s.sentence_id
         WHERE s.content = ?;
        """
        cur.execute(query, (text,))
        return cur.fetchall()

    def get_sentences_with_all_dict_forms(self, dict_form_ids: set) -> set:
        """
        Return the set of sentence_ids that contain *all* of the given dict_form_ids.
        Approach:
         - For each dict_form_id, fetch all sentence_ids containing that form.
         - Intersect those sets across all selected forms.
        """
        if not dict_form_ids:
            return set()

        final_set = None
        for df_id in dict_form_ids:
            sids = self.get_sentence_ids_for_dict_form(df_id)
            sset = set(sids)
            if final_set is None:
                final_set = sset
            else:
                final_set = final_set.intersection(sset)
            if not final_set:
                # Early exit if intersection becomes empty
                return set()

        return final_set if final_set else set()

    def get_sentence_ids_for_dict_form(self, dict_form_id: int) -> list:
        """
        Return a list of all sentence_ids that contain this dict_form_id.
        We rely on the surface_form_sentences + surface_forms + dictionary_forms linkage.
        """
        cur = self._conn.cursor()
        query = """
        SELECT DISTINCT sfs.sentence_id
          FROM surface_form_sentences sfs
          JOIN surface_forms sf ON sfs.surface_form_id = sf.surface_form_id
         WHERE sf.dict_form_id = ?
        """
        cur.execute(query, (dict_form_id,))
        rows = cur.fetchall()
        return [r[0] for r in rows]  # e.g. [12, 13, 52]

    def get_sentence_media_info(self, sentence_id: int) -> Optional[tuple]:
        """
        Return (media_id, start_time, content) for the given sentence_id.
        The logic:
          - Each 'sentence' row references 'text_id'
          - The 'texts' table has 'source' = subtitle_file
          - The 'subtitles' table links that subtitle_file => media_id
        """
        cur = self._conn.cursor()
        query = """
        SELECT sub.media_id, s.start_time, s.content
          FROM sentences s
          JOIN texts t ON s.text_id = t.text_id
          JOIN subtitles sub ON sub.subtitle_file = t.source
         WHERE s.sentence_id = ?
        """
        cur.execute(query, (sentence_id,))
        row = cur.fetchone()
        if not row:
            return None
        return (row[0], row[1], row[2])  # (media_id, start_time, content)

    def get_media_display_name(self, media_id: int) -> str:
        """
        Return a short label (e.g. the file's base name) for a given media_id,
        or something like 'Episode <id>' if not found.
        """
        cur = self._conn.cursor()
        cur.execute("SELECT file_path FROM media WHERE media_id = ?", (media_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return f"Episode {media_id}"

        file_path = row[0]
        # Return only the base filename for display
        return os.path.basename(file_path)

    def get_surface_forms_for_sentence(self, sentence_id: int):
        """Return words for exactly one subtitle sentence by its ID."""
        cur = self._conn.cursor()
        query = """
        SELECT
               sf.surface_form_id,
               sf.surface_form,
               df.dict_form_id,
               df.base_form,
               df.known
          FROM surface_forms sf
          JOIN dictionary_forms df        ON sf.dict_form_id = df.dict_form_id
          JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
         WHERE sfs.sentence_id = ?
        ;
        """
        cur.execute(query, (sentence_id,))
        return cur.fetchall()

    def get_card_by_sentence_id(self, sentence_id: int):
        cur = self._conn.cursor()
        query = """
        SELECT c.sentence_audio, c.image
        FROM cards c
        JOIN sentences s ON c.native_sentence = s.content
        WHERE s.sentence_id = ?
        LIMIT 1;
        """
        cur.execute(query, (sentence_id,))
        return cur.fetchone()

    def get_unknown_dict_forms_in_anki_sentences(self):
        cur = self._conn.cursor()
        query = """
        SELECT DISTINCT df.dict_form_id, df.base_form
        FROM dictionary_forms df
        JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
        JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
        JOIN sentences s ON s.sentence_id = sfs.sentence_id
        JOIN texts t ON s.text_id = t.text_id
        WHERE t.type = 'anki_import' AND df.known = 0;
        """
        cur.execute(query)
        return set(cur.fetchall())

    def get_text_coverage_for_forms(self, dict_form_ids):
        cur = self._conn.cursor()
        form_ids_tuple = tuple(dict_form_ids)
        if not form_ids_tuple:
            return []

        query = f"""
        SELECT t.text_id, df.dict_form_id
        FROM texts t
        JOIN sentences s ON t.text_id = s.text_id
        JOIN surface_form_sentences sfs ON s.sentence_id = sfs.sentence_id
        JOIN surface_forms sf ON sfs.surface_form_id = sf.surface_form_id
        JOIN dictionary_forms df ON sf.dict_form_id = df.dict_form_id
        WHERE t.type = 'text_import'
          AND df.dict_form_id IN ({','.join('?' for _ in form_ids_tuple)})
        GROUP BY t.text_id, df.dict_form_id;
        """
        cur.execute(query, form_ids_tuple)
        results = cur.fetchall()
        coverage_map = {}
        for text_id, df_id in results:
            coverage_map.setdefault(text_id, set()).add(df_id)
        coverage_list = [(text_id, len(df_ids)) for text_id, df_ids in coverage_map.items()]
        coverage_list.sort(key=lambda x: x[1], reverse=True)
        return coverage_list

    def create_study_plan(self, order_index, text_ids, card_ids):
        cur = self._conn.cursor()
        cur.execute("INSERT INTO study_plans (order_index, text_ids, card_ids) VALUES (?, ?, ?)",
                    (order_index, text_ids, card_ids))
        self._conn.commit()
        return cur.lastrowid

    def add_study_plan_step(self, study_plan_id, step_number, card_sentences, text_sentences, words_covered, text_ids):
        table_name = f"study_plan_step_{step_number}"
        cur = self._conn.cursor()
        text_ids_str = ";".join(str(t) for t in text_ids)
        cur.execute(f"""
        INSERT INTO {table_name} (study_plan_id, card_sentences, text_sentences, words_covered, text_ids)
        VALUES (?, ?, ?, ?, ?)
        """, (study_plan_id, card_sentences, text_sentences, words_covered, text_ids_str))
        self._conn.commit()

    def add_study_plan_word(self, study_plan_id, dict_form_id, known):
        cur = self._conn.cursor()
        cur.execute("INSERT INTO study_plan_words (study_plan_id, dict_form_id, known) VALUES (?, ?, ?)",
                    (study_plan_id, dict_form_id, 1 if known else 0))
        self._conn.commit()

    def get_surface_forms_for_text(self, text_id):
        cur = self._conn.cursor()
        query = """
        SELECT sf.surface_form_id, sf.surface_form, df.dict_form_id, df.base_form, df.known
        FROM surface_forms sf
        JOIN dictionary_forms df ON sf.dict_form_id = df.dict_form_id
        JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
        JOIN sentences s ON s.sentence_id = sfs.sentence_id
        WHERE s.text_id = ?
        """
        cur.execute(query, (text_id,))
        return cur.fetchall()

    def get_sentences_for_text(self, text_id):
        cur = self._conn.cursor()
        cur.execute("SELECT sentence_id, content FROM sentences WHERE text_id = ?", (text_id,))
        return cur.fetchall()

    def get_sentences_for_cards(self, card_ids):
        ids = [int(x) for x in card_ids.split(';') if x.strip()]
        if not ids:
            return []
        cur = self._conn.cursor()
        query = f"SELECT card_id, native_sentence FROM cards WHERE card_id IN ({','.join('?' for _ in ids)})"
        cur.execute(query, ids)
        return cur.fetchall()

    def set_dictionary_form_known(self, dict_form_id: int, known: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE dictionary_forms SET known = ? WHERE dict_form_id = ?", (1 if known else 0, dict_form_id))
        self._conn.commit()

    def get_unknown_dict_forms_in_challenge_texts(self):
        cur = self._conn.cursor()
        query = """
        SELECT DISTINCT df.dict_form_id, df.base_form
        FROM dictionary_forms df
        JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
        JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
        JOIN sentences s ON s.sentence_id = sfs.sentence_id
        JOIN texts t ON s.text_id = t.text_id
        WHERE t.type = 'challenge' AND df.known = 0;
        """
        cur.execute(query)
        return set(cur.fetchall())

    def update_text_comprehension(self, text_id: int):
        cur = self._conn.cursor()
        cur.execute("""
        SELECT DISTINCT df.dict_form_id, df.known
        FROM dictionary_forms df
        JOIN surface_forms sf ON df.dict_form_id = sf.dict_form_id
        JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
        JOIN sentences s ON s.sentence_id = sfs.sentence_id
        WHERE s.text_id = ?;
        """, (text_id,))
        forms = cur.fetchall()
        if not forms:
            comprehension = 100.0
        else:
            total = len(forms)
            known_count = sum(1 for f in forms if f[1] == 1)
            comprehension = (known_count / total) * 100.0
        cur.execute("UPDATE texts SET comprehension_percentage = ? WHERE text_id = ?", (comprehension, text_id))
        self._conn.commit()

    def update_unknown_counts_for_dict_form(self, dict_form_id: int):
        cur = self._conn.cursor()
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
        WHERE sentence_id IN (
            SELECT DISTINCT sfs.sentence_id
            FROM surface_forms sf
            JOIN surface_form_sentences sfs ON sf.surface_form_id = sfs.surface_form_id
            WHERE sf.dict_form_id = ?
        );
        """
        cur.execute(update_query, (dict_form_id,))
        self._conn.commit()

    def add_target_content(self, text_id: int, priority: int, comprehension_percentage: float, text_type: str):
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO target_content (text_id, priority, comprehension_percentage, text_type) VALUES (?, ?, ?, ?)",
            (text_id, priority, comprehension_percentage, text_type))
        self._conn.commit()

    def get_or_create_dictionary_form(self, base_form: str, reading: Optional[str] = None,
                                      pos: Optional[str] = None) -> int:
        base_form = remove_surrogates(base_form or "")
        reading = remove_surrogates(reading or "")
        pos = remove_surrogates(pos or "")

        cur = self._conn.cursor()
        cur.execute("SELECT dict_form_id, frequency FROM dictionary_forms WHERE base_form = ?", (base_form,))
        row = cur.fetchone()
        if row:
            dict_form_id, current_freq = row
            new_freq = current_freq + 1
            cur.execute("UPDATE dictionary_forms SET frequency = ? WHERE dict_form_id = ?", (new_freq, dict_form_id))
            self._conn.commit()
            return dict_form_id
        else:
            cur.execute("""
                INSERT INTO dictionary_forms (base_form, reading, pos, frequency)
                VALUES (?, ?, ?, ?)
            """, (base_form, reading, pos, 1))
            self._conn.commit()
            return cur.lastrowid

    def set_compound_known(self, compound_id: int, known: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE compound_forms SET known = ? WHERE compound_id = ?", (1 if known else 0, compound_id))
        self._conn.commit()

    def set_compound_ranking(self, compound_id: int, ranking: Optional[int]):
        cur = self._conn.cursor()
        cur.execute("UPDATE compound_forms SET ranking = ? WHERE compound_id = ?", (ranking, compound_id))
        self._conn.commit()

    def set_kanji_known(self, kanji_id: int, known: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE kanji_entries SET known = ? WHERE kanji_id = ?", (1 if known else 0, kanji_id))
        self._conn.commit()

    def set_kanji_ranking(self, kanji_id: int, ranking: Optional[int]):
        cur = self._conn.cursor()
        cur.execute("UPDATE kanji_entries SET ranking = ? WHERE kanji_id = ?", (ranking, kanji_id))
        self._conn.commit()

    def increment_dictionary_form_frequency(self, dict_form_id: int):
        cur = self._conn.cursor()
        cur.execute("UPDATE dictionary_forms SET frequency = frequency + 1 WHERE dict_form_id = ?", (dict_form_id,))
        self._conn.commit()

    def set_dictionary_form_known(self, dict_form_id: int, known: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE dictionary_forms SET known = ? WHERE dict_form_id = ?", (1 if known else 0, dict_form_id))
        self._conn.commit()

    def add_surface_form(self, dict_form_id: int, surface_form: str, reading: str, pos: Optional[str],
                         sentence_id: int, card_id: int, parse_kanji: bool = True) -> int:
        surface_form = remove_surrogates(surface_form or "")
        reading = remove_surrogates(reading or "")
        pos = remove_surrogates(pos or "")

        cur = self._conn.cursor()
        cur.execute("""
            SELECT surface_form_id, frequency FROM surface_forms
            WHERE dict_form_id = ? AND surface_form = ? AND reading = ? AND (pos = ? OR pos IS NULL)
        """, (dict_form_id, surface_form, reading, pos))
        row = cur.fetchone()
        logging.info(f"Checking for existing surface form: {row}")
        if row:
            surface_form_id, current_freq = row
            new_freq = current_freq + 1
            cur.execute("UPDATE surface_forms SET frequency = ? WHERE surface_form_id = ?", (new_freq, surface_form_id))
            self._conn.commit()
            cur.execute("INSERT INTO surface_form_sentences (surface_form_id, sentence_id) VALUES (?, ?)",
                        (surface_form_id, sentence_id))
            logging.info(f"Linking surface form to sentence: {surface_form_id}, {sentence_id}")
            self._conn.commit()
        else:
            cur.execute("""
                INSERT INTO surface_forms (dict_form_id, surface_form, reading, pos, frequency)
                VALUES (?, ?, ?, ?, ?)
            """, (dict_form_id, surface_form, reading, pos, 1))
            self._conn.commit()
            surface_form_id = cur.lastrowid
            cur.execute("INSERT INTO surface_form_sentences (surface_form_id, sentence_id) VALUES (?, ?)",
                        (surface_form_id, sentence_id))
            logging.info(f"Linking surface form to sentence: {surface_form_id}, {sentence_id}")
            self._conn.commit()

        if parse_kanji and self.contains_kanji(surface_form):
            logging.info(f"Handling compound and kanji for: {surface_form}")
            self._handle_compound_and_kanji(surface_form_id, surface_form, sentence_id, card_id)
            cur.execute("UPDATE surface_forms SET kanji_parsed = 1 WHERE surface_form_id = ?", (surface_form_id,))
            self._conn.commit()

        return surface_form_id

    def contains_kanji(self, text: str) -> bool:
        logging.info(f"Checking for kanji")
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                logging.info(f"Found kanji: {char}")
                return True
        return False

    def _handle_compound_and_kanji(self, surface_form_id: int, compound_text: str, sentence_id: int, card_id: int):
        cur = self._conn.cursor()
        kanji_chars = [c for c in compound_text if '\u4e00' <= c <= '\u9fff']
        if not kanji_chars:
            return
        cur.execute("SELECT compound_id, frequency FROM compound_forms WHERE surface_form_id = ? AND compound_text = ?",
                    (surface_form_id, compound_text))
        row = cur.fetchone()
        if row:
            compound_id, current_freq = row
            new_freq = current_freq + 1
            cur.execute("UPDATE compound_forms SET frequency = ? WHERE compound_id = ?", (new_freq, compound_id))
            self._conn.commit()
        else:
            cur.execute("""
                INSERT INTO compound_forms (surface_form_id, compound_text, frequency, known)
                VALUES (?, ?, ?, ?)
            """, (surface_form_id, compound_text, 1, 0))
            self._conn.commit()
            compound_id = cur.lastrowid

        for kchar in kanji_chars:
            cur.execute("SELECT kanji_id, frequency FROM kanji_entries WHERE compound_id = ? AND kanji_char = ?",
                        (compound_id, kchar))
            row = cur.fetchone()
            if row:
                kanji_id, current_freq = row
                new_freq = current_freq + 1
                cur.execute("UPDATE kanji_entries SET frequency = ? WHERE kanji_id = ?", (new_freq, kanji_id))
                self._conn.commit()
            else:
                cur.execute("""
                    INSERT INTO kanji_entries (compound_id, kanji_char, frequency, known)
                    VALUES (?, ?, ?, ?)
                """, (compound_id, kchar, 1, 0))
                self._conn.commit()
                kanji_id = cur.lastrowid

            cur.execute("""
                INSERT INTO kanji_linkage (kanji_id, surface_form_id, sentence_id, card_id)
                VALUES (?, ?, ?, ?)
            """, (kanji_id, surface_form_id, sentence_id, card_id))
            self._conn.commit()

    def parse_pending_kanji(self):
        """Process surface forms that haven't had their kanji parsed yet."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT surface_form_id, surface_form FROM surface_forms WHERE kanji_parsed = 0"
        )
        rows = cur.fetchall()
        for sf_id, text in rows:
            if not self.contains_kanji(text):
                cur.execute(
                    "UPDATE surface_forms SET kanji_parsed = 1 WHERE surface_form_id = ?",
                    (sf_id,),
                )
                continue

            cur.execute(
                "SELECT sentence_id FROM surface_form_sentences WHERE surface_form_id = ?",
                (sf_id,),
            )
            sentence_rows = cur.fetchall() or [(0,)]
            for (sent_id,) in sentence_rows:
                self._handle_compound_and_kanji(sf_id, text, sent_id, None)

            cur.execute(
                "UPDATE surface_forms SET kanji_parsed = 1 WHERE surface_form_id = ?",
                (sf_id,),
            )
        self._conn.commit()

    def count_deferred_kanji(self) -> int:
        """Return the number of surface forms waiting for kanji parsing."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM surface_forms WHERE kanji_parsed = 0"
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def increment_surface_form_frequency(self, surface_form_id: int):
        cur = self._conn.cursor()
        cur.execute("UPDATE surface_forms SET frequency = frequency + 1 WHERE surface_form_id = ?", (surface_form_id,))
        self._conn.commit()

    def set_surface_form_known(self, surface_form_id: int, known: bool):
        cur = self._conn.cursor()
        cur.execute("UPDATE surface_forms SET known = ? WHERE surface_form_id = ?",
                    (1 if known else 0, surface_form_id))
        self._conn.commit()

    def get_or_create_dictionary_info(self, dictionary_name: str) -> int:
        cur = self._conn.cursor()
        cur.execute("INSERT OR IGNORE INTO dictionary_info (dictionary_name) VALUES (?)", (dictionary_name,))
        self._conn.commit()
        cur.execute("SELECT dictionary_id FROM dictionary_info WHERE dictionary_name = ?", (dictionary_name,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def insert_dictionary_word(self, dictionary_id: int, lemma: str, pos: str) -> int:
        cur = self._conn.cursor()
        cur.execute("INSERT INTO dictionary_words (dictionary_id, lemma, pos) VALUES (?, ?, ?)",
                    (dictionary_id, lemma, pos))
        self._conn.commit()
        return cur.lastrowid

    def insert_dictionary_definition(self, dictionary_word_id: int, definition: str):
        cur = self._conn.cursor()
        cur.execute("INSERT INTO dictionary_definitions (dictionary_word_id, definition) VALUES (?, ?)",
                    (dictionary_word_id, definition))
        self._conn.commit()

    def import_mdx_dictionary(self, mdx_path: str, dictionary_name: str):
        script_root = os.path.dirname(__file__)
        base_name = os.path.splitext(os.path.basename(mdx_path))[0]

        result = subprocess.run(
            ["mdict", "-x", mdx_path, "--exdb"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            cwd=script_root
        )

        exdb_path = os.path.join(script_root, f"{base_name}.db")
        if not os.path.exists(exdb_path):
            raise FileNotFoundError(f"Extracted database {exdb_path} not found.")

        dictionary_id = self.get_or_create_dictionary_info(dictionary_name)

        for lemma, reading, definition in self.parse_dictionary_db(exdb_path):
            pos = "Unknown"
            dictionary_word_id = self.insert_dictionary_word(dictionary_id, lemma, pos)
            self.insert_dictionary_definition(dictionary_word_id, definition)

        print(f"Dictionary '{dictionary_name}' imported from {mdx_path}.")

    def parse_dictionary_db(self, exdb_path: str):
        conn = sqlite3.connect(exdb_path)
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cur.fetchall()]
        print("Tables in extracted DB:", tables)

        cur.execute("SELECT entry, paraphrase FROM mdx;")

        lemma_pattern = re.compile(r'<h2 class="midashigo" title="([^"]+)">', re.DOTALL)
        tag_pattern = re.compile(r'<.*?>', flags=re.DOTALL)

        for reading, paraphrase_html in cur.fetchall():
            reading = reading.strip()

            lemma_match = lemma_pattern.search(paraphrase_html)
            if lemma_match:
                lemma = lemma_match.group(1).strip()
            else:
                lemma = reading

            text = html.unescape(paraphrase_html)
            text = tag_pattern.sub('', text).strip()
            text = re.sub(r'読み方：.*?\n?', '', text).strip()

            definition = text.strip()

            yield (lemma, reading, definition)

        conn.close()

    def close(self):
        self._conn.close()
