import re


def normalize_filename(stem: str) -> str:
    """Normalize a filename by removing bracketed tags, replacing separators and
    collapsing whitespace."""
    temp = re.sub(r"\[.*?\]", "", stem)
    temp = temp.replace('-', ' ')
    temp = temp.replace('_', ' ')
    temp = re.sub(r"\s+", " ", temp)
    return temp.strip().lower()


def parse_filename_for_show_episode(stem: str):
    """Return (title, season, episode) parsed from filename stem.

    Season and episode are integers or ``None`` when not found.
    """
    name = normalize_filename(stem)

    # remove year like (2022) or resolution info like (1080p) etc
    # strip parenthesized groups commonly containing year or resolution
    name = re.sub(r"\([^)]*(?:\d{3,4}p|(?:19|20)\d{2}|x\d{3})[^)]*\)", "", name, flags=re.I)
    name = re.sub(r"\([^)]*blu[- ]?ray[^)]*\)", "", name, flags=re.I)
    name = name.strip()

    patterns = [
        re.compile(r"^(?P<title>.+?)\bs(?P<season>\d{1,2})e(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\b(?:episode|ep)\s*(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\b(?P<episode>\d{1,3})$", re.I),
    ]

    for pat in patterns:
        m = pat.search(name)
        if m:
            title = m.group('title').strip()
            season = int(m.group('season')) if 'season' in m.groupdict() and m.group('season') else None
            episode = int(m.group('episode')) if 'episode' in m.groupdict() and m.group('episode') else None
            return title, season, episode

    return name, None, None
