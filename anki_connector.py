import requests
import json
import logging

from charset_normalizer.md import Optional, List


class AnkiConnector:
    def __init__(self, host="127.0.0.1", port=8765):
        self.url = f"http://{host}:{port}"
        self.version = 6
        logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger("AnkiConnector")

    def invoke(self, action: str, **params):
        request_payload = {
            "action": action,
            "version": self.version,
            "params": params
        }
        self.logger.debug(f"Invoking {action} with params: {params}")
        try:
            response = requests.post(self.url, json=request_payload).json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to connect to AnkiConnect: {e}")
            return None

        if 'error' in response and response['error'] is not None:
            self.logger.error(f"AnkiConnect error: {response['error']}")
            return None

        return response.get('result')

    def invoke_raw(self, payload: dict):
        response = requests.post(self.url, json=payload).json()
        return response

    def get_decks(self):
        """
        Returns a dictionary of deck names to their IDs using the 'deckNamesAndIds' action.
        """
        decks = self.invoke("deckNames")  # returns {"Basic": 123456789, "Core 2k/6k": 987654321, ...}
        return decks if decks else {}



    #test_cards = [1494819274523, 1494819274524]
    #response = are_due_cards(test_cards)
    #print(response)

    def get_cards(self, deck_name: str):
        cards = self.invoke("findCards", query=f"deck:{deck_name}")  # returns a list of card IDs
        logging.debug(f"Found {len(cards)} cards in deck {deck_name}")
        return cards if cards else {}

    def add_note(self, deck_name: str, model_name: str, fields: dict, tags=None, audio=None, image=None) -> Optional[
        int]:
        """
        Add a single note to a given deck using a specified model. Returns the note_id if successful.

        fields: A dict mapping field names to their values, e.g. {"Front": "こんにちは", "Back": "Hello"}
        tags: A list of tags to apply to the note, e.g. ["Japanese", "N5"]
        audio/image: Optional media attachments conforming to AnkiConnect's specification.

        Returns:
            note_id (int) if successful, otherwise None.
        """
        if tags is None:
            tags = []
        note = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "tags": tags
        }
        if audio:
            note["audio"] = [audio]
        if image:
            note["picture"] = [image]

        result = self.invoke("addNote", note=note)
        if result is None:
            self.logger.error("Failed to add note.")
            return None

        # 'addNote' returns the note_id of the newly created note.
        note_id = result
        return note_id

    def change_deck(self, card_ids: List[int], deck_name: str):
        """
        Change the deck for the given card_ids to the specified deck_name.

        card_ids: A list of card IDs to move.
        deck_name: The name of the target deck.

        Returns:
            The result of the AnkiConnect "changeDeck" action (usually True) or None if failed.
        """
        if not card_ids:
            self.logger.warning("No card_ids provided to change_deck.")
            return None

        return self.invoke("changeDeck", cards=card_ids, deck=deck_name)

    def create_filtered_deck(self, deck_name: str, search_query: str, order=0, limit=1):
        """Create or replace a filtered deck with the given name and search query."""
        params = {
            "deckName": deck_name,
            "query": search_query,
            "order": order,
            "limit": limit
        }
        return self.invoke("createFilteredDeck", **params)

    def gui_deck_study(self, deck_name: str):
        return self.invoke("guiDeckStudy", name=deck_name)

    def gui_show_question(self):
        return self.invoke("guiShowQuestion")

    def gui_answer_card(self, ease: int):
        return self.invoke("guiAnswerCard", ease=ease)

    def find_cards(self, query: str):
        return self.invoke("findCards", query=query)

    def find_due_cards(self, card_ids: list):
        return self.invoke("areDue", cards=card_ids)

    def get_card_info(self, card_ids: list):
        return self.invoke("cardsInfo", cards=card_ids)



    def increment_card_review(self, card_id: int, response: str = 'good'):
        """
        Simulate a review of a single card:
        - response: 'good' or 'again' (maps to Anki ease 3 or 1)
        """
        # Map our response to Anki ease
        # 1=Again, 2=Hard, 3=Good, 4=Easy
        ease_map = {'again': 1, 'good': 3}
        ease = ease_map.get(response, 3)

        # Create a filtered deck just for this card to ensure it's the next one shown
        filtered_deck_name = f"Temp_Review_Deck_{card_id}"
        # Search query that should return only this specific card
        query = f"cid:{card_id}"

        self.logger.info(f"Creating filtered deck to isolate card {card_id}")
        self.create_filtered_deck(deck_name=filtered_deck_name, search_query=query)

        # Start studying this filtered deck
        self.gui_deck_study(filtered_deck_name)

        # Show the question
        show_res = self.gui_show_question()
        if show_res is None:
            self.logger.error("Failed to show question for the card.")
            return None

        # Answer the card with the chosen ease
        answer_res = self.gui_answer_card(ease)
        if answer_res is None:
            self.logger.error("Failed to answer the card.")
            return None

        # Retrieve updated card info
        card_info = self.get_card_info([card_id])
        if card_info:
            return card_info[0]
        return None
