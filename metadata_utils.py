import os
import logging
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

# These globals should be configured by the application
TMDB_API_KEY = None
DB_MANAGER = None


def fetch_and_store_metadata(media_id, show, season, episode):
    """Fetch metadata for an episode from TMDb and store it in the DB."""
    if not TMDB_API_KEY or DB_MANAGER is None:
        logger.info("TMDb API key or DB manager not configured; skipping metadata fetch")
        return

    try:
        # Search for the show by name
        search_resp = requests.get(
            "https://api.themoviedb.org/3/search/tv",
            params={"query": show, "api_key": TMDB_API_KEY},
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("results") or []
        if not results:
            logger.info(f"TMDb: no results for show '{show}'")
            return

        show_id = results[0].get("id")
        poster_path = results[0].get("poster_path")
        if show_id is None:
            logger.info(f"TMDb: missing show id for '{show}'")
            return

        # Fetch episode details
        ep_resp = requests.get(
            f"https://api.themoviedb.org/3/tv/{show_id}/season/{season}/episode/{episode}",
            params={"api_key": TMDB_API_KEY},
        )
        ep_resp.raise_for_status()
        ep_data = ep_resp.json()
        overview = ep_data.get("overview", "")
        still_path = ep_data.get("still_path")

        image_path = still_path or poster_path
        saved_path = None
        if image_path:
            image_url = f"https://image.tmdb.org/t/p/w500{image_path}"
            try:
                img_resp = requests.get(image_url)
                img_resp.raise_for_status()
                Path("thumbnails").mkdir(exist_ok=True)
                ext = os.path.splitext(image_path)[1] or ".jpg"
                saved_path = os.path.join("thumbnails", f"{media_id}{ext}")
                with open(saved_path, "wb") as f:
                    f.write(img_resp.content)
            except Exception as e:
                logger.warning(f"Failed to download image: {e}")
                saved_path = None

        DB_MANAGER.update_media_metadata(media_id, thumbnail_path=saved_path, description=overview)
    except Exception:
        logger.exception("Failed fetching metadata from TMDb")
