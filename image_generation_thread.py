from PyQt5.QtCore import QThread, pyqtSignal
import uuid
import base64
import openai
import requests


def generate_prompt_for_word(word: str) -> str:
    """Return a simple prompt string for the given word."""
    return f"Create an illustrative image that clearly conveys the meaning of '{word}'."


class ImageGenerationThread(QThread):
    """Worker thread that generates an image using OpenAI and stores it via AnkiConnect."""

    done = pyqtSignal(int, str)  # dict_form_id, filename
    error = pyqtSignal(str)

    def __init__(self, word_text: str, dict_form_id: int, api_key: str, anki_connector):
        super().__init__()
        self.word = word_text
        self.dict_form_id = dict_form_id
        self.api_key = api_key
        self.anki = anki_connector

    def run(self):
        openai.api_key = self.api_key
        prompt = generate_prompt_for_word(self.word)
        try:
            response = openai.Image.create(prompt=prompt, n=1, size="512x512")
            image_url = response["data"][0]["url"]
            image_data = requests.get(image_url).content
        except Exception as e:
            self.error.emit(f"Image generation failed: {e}")
            return

        filename = f"ai_image_{uuid.uuid4().hex}.png"
        try:
            b64_data = base64.b64encode(image_data).decode("utf-8")
            res = self.anki.invoke("storeMediaFile", filename=filename, data=b64_data)
            if res is None:
                raise Exception("Anki storeMediaFile failed")
        except Exception as e:
            self.error.emit(f"Failed saving image: {e}")
            return

        self.done.emit(self.dict_form_id, filename)
