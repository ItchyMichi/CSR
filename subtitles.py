import os
import re
from typing import List, Dict

class Subtitle:
    def __init__(self, start_time: float, end_time: float, text: str):
        self.start_time = start_time
        self.end_time = end_time
        self.text = text.strip()  # Strip trailing newlines


class SubtitleManager:
    def __init__(self):
        self.subtitles = []

    def load_subtitles(self, file_path):
        if file_path.endswith('.srt'):
            return self._load_srt(file_path)
        elif file_path.endswith('.vtt'):
            return self._load_vtt(file_path)
        else:
            return False

    def reload_subtitles(self, file_path):
        return self.load_subtitles(file_path)

    def _load_srt(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n', re.DOTALL)
        matches = pattern.findall(content)

        self.subtitles = []
        for match in matches:
            index, start_time, end_time, text = match
            start_seconds = self._convert_time_to_seconds(start_time)
            end_seconds = self._convert_time_to_seconds(end_time)
            self.subtitles.append({
                'start_time': start_seconds,
                'end_time': end_seconds,
                'text': text.replace('\n', ' ')
            })
        return True

    def _load_vtt(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        pattern = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\n(.*?)\n\n', re.DOTALL)
        matches = pattern.findall(content)

        self.subtitles = []
        for match in matches:
            start_time, end_time, text = match
            start_seconds = self._convert_time_to_seconds(start_time.replace('.', ','))
            end_seconds = self._convert_time_to_seconds(end_time.replace('.', ','))
            self.subtitles.append({
                'start_time': start_seconds,
                'end_time': end_seconds,
                'text': text.replace('\n', ' ')
            })
        return True

    def _convert_time_to_seconds(self, time_str):
        h, m, s = time_str.split(':')
        s, ms = s.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    def get_subtitles(self):
        return self.subtitles

    def get_current_subtitle(self, current_time):
        for subtitle in self.subtitles:
            if subtitle['start_time'] <= current_time <= subtitle['end_time']:
                return subtitle['text']
        return ""
