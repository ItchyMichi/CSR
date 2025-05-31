import re


def normalize_filename(stem: str) -> str:
    """
    Normalize a filename by:
      1. Removing tags in square brackets (e.g., [SubsPlease], [E7479F2F]).
      2. Removing common quality/source words (480p, 720p, 1080p, 2160p, 2160p, WEBRip, WEB-DL, HDTV, BluRay, x264, x265).
      3. Replacing dots, underscores, and hyphens with spaces.
      4. Collapsing multiple spaces, lowercasing, and stripping.
    """
    # 1. Remove any content inside square brackets
    temp = re.sub(r"\[.*?\]", "", stem)

    # 2. Remove common quality/source tags outside of brackets
    temp = re.sub(
        r"\b(480p|720p|1080p|2160p|WEBRip|WEB[- ]DL|HDTV|Blu[- ]?Ray|x264|x265)\b",
        "",
        temp,
        flags=re.I
    )

    # 3. Replace dots, underscores, and hyphens with spaces
    temp = temp.replace(".", " ").replace("_", " ").replace("-", " ")

    # 4. Collapse multiple spaces and lowercase
    temp = re.sub(r"\s+", " ", temp).strip().lower()
    return temp


def parse_filename_for_show_episode(stem: str):
    """
    Return (title, season, episode) parsed from a filename stem.

    Season and episode are returned as integers when found, or None if not found.
    If no explicit season is detected but an episode is found, season defaults to 1.
    """
    # First, normalize: remove bracketed tags, quality/source words, and unify separators
    name = normalize_filename(stem)

    # Next, strip out parenthesized groups that usually contain years, resolution info, etc.
    # e.g., (2022), (1080p), (x264), (BluRay)
    name = re.sub(
        r"\([^)]*(?:\d{3,4}p|(?:19|20)\d{2}|x\d{3}|blu[- ]?ray)[^)]*\)",
        "",
        name,
        flags=re.I
    ).strip()

    # Remove any leftover parentheses (e.g., empty "()")
    name = re.sub(r"\([^)]*\)", "", name).strip()

    # Define regex patterns in order of precedence
    patterns = [
        # 1. Standard "SxxEyy" (e.g., "S01E01", "S1.E1", "S1 E1")
        re.compile(
            r"^(?P<title>.*?)[\s._-]*s(?P<season>\d{1,2})[\s._-]*e(?P<episode>\d{1,3})\b",
            re.I
        ),
        # 1a. "S<season> Ep<episode>" (e.g., "S1 Ep01", "S01 ep.01", "S2 ep 05")
        re.compile(
            r"""
            ^(?P<title>.*?)               # everything up to "S<season> ep<episode>"
            [\s._-]*                      # optional separators
            s(?P<season>\d{1,2})          # 'S' + 1–2 digit season
            [\s._-]*                      # optional separators
            (?:ep|episode)                # literal 'ep' or 'episode'
            [\s\.]*                       # optional spaces or dots
            (?P<episode>\d{1,3})\b        # 1–3 digit episode, then word boundary
            """,
            re.I | re.VERBOSE
        ),
        # 2. "1x01" format (e.g., "3x07", "10x12")
        re.compile(
            r"^(?P<title>.*?)[\s._-]*(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b",
            re.I
        ),
        # 3. "Season X Episode Y" (long form), e.g., "Show Name Season 2 Episode 10"
        re.compile(
            r"^(?P<title>.*?)[\s._-]*season\s*(?P<season>\d{1,2})\s*(?:episode|ep)\s*(?P<episode>\d{1,3})\b",
            re.I
        ),
        # 4. Numeric-only episode (no season), e.g., "Kaijuu 8 gou 01"
        re.compile(
            r"^(?P<title>.*?)[\s._-]+(?P<episode>\d{1,2})\b$",
            re.I
        ),
        # 5. "Episode Y" only (without a season), e.g., "MiniSeries Ep 5"
        re.compile(
            r"^(?P<title>.*?)[\s._-]*(?:episode|ep)\s*(?P<episode>\d{1,3})\b",
            re.I
        ),
        # 6. Combined 3- or 4-digit code, e.g., "101" → S1E01, "1001" → S10E01
        re.compile(
            r"^(?P<title>.*?)[\s._-]*(?P<season>\d{1,2})(?P<episode>\d{2})\b",
            re.I
        ),
    ]

    # Attempt each pattern in sequence
    for pat in patterns:
        m = pat.search(name)
        if m:
            title = m.group("title").strip()
            season = None
            episode = None

            if "season" in m.groupdict() and m.group("season"):
                season = int(m.group("season"))

            if "episode" in m.groupdict() and m.group("episode"):
                episode = int(m.group("episode"))



            return title, season, episode

    # If no pattern matched, return the entire normalized name as title
    return name, None, None
