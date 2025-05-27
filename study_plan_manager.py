import configparser
import datetime
from typing import List, Tuple, Dict

DEFAULT_EF = 2.5  # Ease factor no longer directly used, as Anki handles intervals
MIN_INTERVAL = 1  # Not used locally, but kept as a reference


class StudyPlanManager:
    def __init__(self, db_manager, anki_connector, config_path="config.ini"):
        """
        Initialize the StudyPlanManager with references to the database and Anki connector.
        """
        self.db = db_manager
        self.anki = anki_connector
        self.config = configparser.ConfigParser()
        self.config.read(config_path)

        # Load configuration
        self.daily_word_goal = int(self.config.get('StudyPlan', 'daily_word_goal', fallback='20'))
        self.recommended_texts_count = int(self.config.get('StudyPlan', 'recommended_texts_count', fallback='5'))
        self.n_plus_one_threshold = int(self.config.get('StudyPlan', 'n_plus_one_threshold', fallback='1'))
        self.unlocking_word_priority_factor = float(
            self.config.get('StudyPlan', 'unlocking_word_priority_factor', fallback='2.0'))

    def get_daily_study_plan(self) -> Dict[str, List]:
        """
        Orchestrate the daily plan:
        1. Select new words to introduce to Anki (if needed).
        2. Sync those words to Anki, ensuring each has a corresponding card in "All Words".
        3. Move the newly selected cards into the "Study Deck" in Anki.
        4. Query Anki for due cards in the "Study Deck".
        5. Optionally recommend texts for further reading.

        Returns a dict:
        {
          'new_words': [word_id, ...],
          'due_cards': [anki_card_id, ...],
          'recommended_texts': [(text_id, score), ...]
        }
        """
        # 1. Select words for study
        new_words = self.select_words_for_study(self.daily_word_goal)

        # 2. Sync words to Anki (ensure each word has a card in "All Words")
        self.sync_words_to_anki(new_words)

        # Retrieve local card_ids and then their anki_card_ids
        new_card_ids = [self.db.get_card_id_for_word(w_id) for w_id in new_words if
                        self.db.get_card_id_for_word(w_id) is not None]
        anki_card_ids = [self.db.get_card_anki_id(c_id) for c_id in new_card_ids if
                         self.db.get_card_anki_id(c_id) is not None]

        # 3. Move the selected cards into the Study Deck
        self.move_cards_to_study_deck(anki_card_ids)

        # 4. Get due cards from Anki's Study Deck
        due_cards = self.get_due_cards_from_anki()

        # 5. Recommend texts based on target words
        recommended_texts = self._get_recommended_texts(new_words, self.recommended_texts_count)

        return {
            'new_words': new_words,
            'due_cards': due_cards,
            'recommended_texts': recommended_texts
        }

    def select_words_for_study(self, limit: int) -> List[int]:
        """
        Determine which words to introduce into the Study Deck today.
        This logic can be based on unknown words, frequency, or unlocking sentences.
        For simplicity, just pick the first 'limit' unknown words.
        """
        unknown_words = self.db.get_unknown_words()  # [(word_id, lemma), ...]
        selected = [w_id for w_id, lemma in unknown_words[:limit]]
        return selected

    def sync_words_to_anki(self, word_ids: List[int]):
        """
        Ensure each word has a corresponding Anki card in the "All Words" deck.
        If not present, create it in both the local DB and Anki.
        """
        all_words_deck_id = self.db.ensure_all_words_deck_exists()

        for w_id in word_ids:
            card_id = self.db.get_card_id_for_word(w_id)
            if card_id is None:
                # Create a word card in the All Words deck
                card_id = self.db.create_word_card_for_all_words_deck(w_id)

            anki_card_id = self.db.get_card_anki_id(card_id)
            if anki_card_id is None:
                # If no anki_card_id, create the card in Anki
                lemma, reading, pos = self.db.get_word_data_for_card(w_id)
                front = lemma
                back = f"Reading: {reading}\nPOS: {pos}"
                # We'll assume a "Basic" model and optional tags
                new_anki_card_id = self.anki.add_note("All Words", "Basic", {"Front": front, "Back": back},
                                                      tags=["auto_generated"])
                if new_anki_card_id is None:
                    continue
                # The add_note method typically returns a note_id, from which we get card_ids.
                # We'll have to find the created card. Since add_note might return a note_id, we need to find the card_ids for that note.
                # For simplicity, assume new_anki_card_id is actually a card_id returned by a custom add_note method.
                # If it's a note_id, you'd use anki.get_card_info(...) after searching by note_id to find the card.
                # Let's assume add_note returns a note_id and we find its cards:
                if isinstance(new_anki_card_id, int):
                    # find card(s) associated with this note:
                    card_ids = self.anki.find_cards(f"nid:{new_anki_card_id}")
                    if card_ids:
                        # We'll just take the first card associated with the note
                        new_anki_card_id = card_ids[0]
                        self.db.set_card_anki_id(card_id, new_anki_card_id)


    def get_due_cards_from_anki(self) -> List[int]:
        """
        Query Anki for cards due in the "Study Deck".
        """
        return self.anki.find_cards("deck:Study Deck is:due")

    def run_study_session(self, due_cards: List[int]) -> Dict[int, str]:
        """
        Present due cards to the user (via GUI), get responses ('good' or 'again'),
        and simulate the review in Anki.
        Returns a dict mapping anki_card_id -> response.
        """
        responses = {}
        for c_id in due_cards:
            # Here you'd display the card to the user and get a response.
            # For simplicity, assume all are 'good':
            # In a real scenario, integrate with GUI methods to get actual user input.
            user_response = 'good'
            responses[c_id] = user_response

        # Update in Anki
        for c_id, resp in responses.items():
            self.anki.increment_card_review(c_id, resp)

        # After incrementing card reviews, update local metadata
        self.update_local_metadata_after_review(list(responses.keys()))

        return responses

    def update_local_metadata_after_review(self, card_ids: List[int]):
        """
        After updating card reviews in Anki, fetch updated info (tags, known status)
        and store it locally.
        """
        card_info = self.anki.get_card_info(card_ids)
        if not card_info:
            return

        for info in card_info:
            c_id = info['cardId']
            # Retrieve the associated word_id
            word_id = self.db.get_word_id_by_anki_card_id(c_id)
            if word_id is None:
                continue
            # Check tags or other fields to determine if the word is now known
            if "known" in info.get('tags', []):
                self.db.set_word_known(word_id, True)

    def sync_word_tags_with_anki(self, word_id: int):
        """
        Sync local tags for a word to Anki. If the word is known, add "known" tag, etc.
        """
        card_id = self.db.get_card_id_for_word(word_id)
        if card_id is None:
            return
        anki_card_id = self.db.get_card_anki_id(card_id)
        if anki_card_id is None:
            return
        tags = []
        if self.db.is_word_known(word_id):
            tags.append("known")
        if tags:
            # add tags to the note associated with this card
            # first get card info
            info = self.anki.get_card_info([anki_card_id])
            if info:
                note_id = info[0]['note']
                self.anki.add_tags_to_notes([note_id], " ".join(tags))

    def _get_recommended_texts(self, target_word_ids: List[int], limit: int) -> List[Tuple[int, float]]:
        """
        Uses the database to compute text suitability and coverage.
        Same logic as before.
        """
        texts = self.db.get_all_text_ids()
        scores = []

        for t_id in texts:
            suitability = self.db.compute_text_suitability(t_id)
            coverage = self.db.get_coverage_of_words_in_text(t_id, target_word_ids)
            final_score = coverage * 2 + suitability
            scores.append((t_id, final_score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]

    def update_study_config(self, daily_word_goal=None, recommended_texts_count=None, n_plus_one_threshold=None,
                            unlocking_word_priority_factor=None):
        """
        Update study configuration parameters.
        """
        if daily_word_goal is not None:
            self.config.set('StudyPlan', 'daily_word_goal', str(daily_word_goal))
        if recommended_texts_count is not None:
            self.config.set('StudyPlan', 'recommended_texts_count', str(recommended_texts_count))
        if n_plus_one_threshold is not None:
            self.config.set('StudyPlan', 'n_plus_one_threshold', str(n_plus_one_threshold))
        if unlocking_word_priority_factor is not None:
            self.config.set('StudyPlan', 'unlocking_word_priority_factor', str(unlocking_word_priority_factor))

        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)

        # Reinitialize to load updated configs
        self.__init__(self.db, self.anki, "config.ini")
