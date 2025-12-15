import requests
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# --------------------------------------------------
# Helper : Set RJM Group Title
# --------------------------------------------------
def set_group_title(meta_data, title):
    meta_data = re.sub(r'group-title=".*?"', '', meta_data)
    return f'{meta_data} group-title="RJM | {title}"'

# --------------------------------------------------
# Main Function
# --------------------------------------------------
def filter_and_split_playlist(playlist_url, file_live, file_series, file_movies, file_tvshows):
    print(f"Downloading playlist from: {playlist_url}")

    try:
        response = requests.get(playlist_url, timeout=30)
        response.raise_for_status()
        content = response.text
    except requests.exceptions.RequestException as e:
        print(f"Error downloading playlist: {e}")
        return

    lines = content.splitlines()

    live_items = []
    movie_items = []
    season_grouping = defaultdict(list)

    DEFAULT_LOGO = "https://simgbb.com/avatar/dw9KLnpdGh3y.jpg"

    for i in range(len(lines)):
        line = lines[i]

        if not line.startswith("#EXTINF"):
            continue

        if "telugu" not in line.lower() and "teulugu" not in line.lower():
            continue

        if i + 1 >= len(lines):
            continue

        stream_url = lines[i + 1].strip()

        # ---------------- CATEGORY DETECTION ----------------
        is_live = "/live/" in stream_url
        is_movie = "/movie/" in stream_url
        is_series = "/series/" in stream_url

        if not (is_live or is_movie or is_series):
            if stream_url.endswith(".ts"):
                is_live = True
            elif re.search(r"S\d+|E\d+", line, re.IGNORECASE):
                is_series = True
            else:
                is_movie = True

        # ---------------- METADATA CLEAN ----------------
        line = line.replace('tvg-id=""', '')
        line = re.sub(r'group-title=".*?"', '', line)
        line = re.sub(r'tvg-name=".*?"', '', line)

        parts = line.rsplit(",", 1)
        if len(parts) != 2:
            continue

        meta_data, name = parts

        # ---------------- LOGO FIX ----------------
        if 'tvg-logo=""' in meta_data:
            meta_data = meta_data.replace('tvg-logo=""', f'tvg-logo="{DEFAULT_LOGO}"')
        elif 'tvg-logo=' not in meta_data:
            meta_data = f'{meta_data} tvg-logo="{DEFAULT_LOGO}"'

        meta_data = " ".join(meta_data.split())

        # ---------------- MOVIE ANALYSIS ----------------
        is_cam = False
        year = 0

        if is_movie:
            if re.search(r'\bCAM\b|\(CAM\)', name, re.IGNORECASE):
                is_cam = True

            years = re.findall(r'\b(?:19|20)\d{2}\b', name)
            if years:
                year = int(years[-1])

        # ---------------- NAME CLEAN ----------------
        patterns = [
            r"Telugu:\s*", r"\(\s*Telugu\s*\)",
            r"Cric\s*[|]*", r"Tl\s*[|]*", r"In:\s*",
            r"24/7\s*:*", r"\(FHD\)", r"\(4K\)", r"⁴ᵏ", r"\|+"
        ]

        for p in patterns:
            name = re.sub(p, " ", name, flags=re.IGNORECASE)

        if is_movie:
            name = re.sub(r"\bTelugu\b", " ", name, flags=re.IGNORECASE)

        name = name.replace("_", " ").replace("-", " ").replace(".", "").replace('"', ',')
        name = " ".join(name.split()).title()

        name = re.sub(r"\bHd\b", "HD", name, flags=re.IGNORECASE)
        name = re.sub(r"\bSd\b", "SD", name, flags=re.IGNORECASE)
        name = re.sub(r"\bTv\b", "TV", name, flags=re.IGNORECASE)
        name = re.sub(r"\bCam\b", "CAM", name, flags=re.IGNORECASE)

        # ---------------- STREAM ID ----------------
        try:
            stream_id = int(re.findall(r'/(\d+)(?:\.\w+)?$', stream_url)[0])
        except Exception:
            stream_id = 0

        item_data = {
            "url": stream_url,
            "stream_id": stream_id,
            "year": year,
            "is_cam": is_cam,
            "clean_name": re.sub(r'\bCAM\b|\(CAM\)', '', name, flags=re.IGNORECASE).lower().strip(),
            "display_name": name,
            "meta": meta_data
        }

        # ---------------- DISTRIBUTION ----------------
        if is_live:
            meta = set_group_title(meta_data, "Live")
            live_items.append((f"{meta},{name}", stream_url))

        elif is_movie:
            meta = set_group_title(meta_data, "Movies")
            item_data["line"] = f"{meta},{name}"
            movie_items.append(item_data)

        elif is_series:
            meta = set_group_title(meta_data, "Web Series")
            item_data["line"] = f"{meta},{name}"

            m = re.search(r'^(.*?)\s*S(\d+)', name, re.IGNORECASE)
            if m:
                show, season = m.group(1).lower(), m.group(2)
            else:
                show, season = name.lower(), "00"

            season_grouping[(show, season)].append(item_data)

    # ================= POST PROCESSING =================

    # ---------- MOVIES (DEDUP) ----------
    movie_items.sort(key=lambda x: (x["year"], x["stream_id"]), reverse=True)

    final_movies = {}
    for m in movie_items:
        key = m["clean_name"]
        if key not in final_movies or (final_movies[key]["is_cam"] and not m["is_cam"]):
            final_movies[key] = m

    movie_list = [(m["line"], m["url"]) for m in final_movies.values()]

    # ---------- SERIES / TV SHOWS ----------
    series_list = []
    tvshows_list = []

    for episodes in season_grouping.values():
        episodes.sort(key=lambda x: x["stream_id"], reverse=True)
        if len(episodes) >= 25:
            for e in episodes:
                meta, name = e["line"].rsplit(",", 1)
                meta = set_group_title(meta, "TV Shows")
                tvshows_list.append((f"{meta},{name}", e["url"]))
        else:
            series_list.extend([(e["line"], e["url"]) for e in episodes])

    # ---------- SAVE ----------
    save_file(file_live, live_items)
    save_file(file_movies, movie_list)
    save_file(file_series, series_list)
    save_file(file_tvshows, tvshows_list)

# --------------------------------------------------
# Save Function
# --------------------------------------------------
def save_file(filename, items):
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    timestamp = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    content = [
        '#EXTM3U billed-msg="RJM Tv - RJMBTS Network"',
        "# RJMS - RJMBTS Network",
        "# Scripted & Updated by Kittujk",
        f"# Last Updated: {timestamp}",
        "#EXTM3U",
    ]

    for info, url in items:
        content.append(info)
        content.append(url)

    if items:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        print(f"Saved {filename}: {len(items)} items")
    else:
        print(f"No data for {filename}")

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
HOST_URL = "https://webhop.live"
USERNAME = os.getenv("IPTV_USER", "juno123")
PASSWORD = os.getenv("IPTV_PASS", "juno123")

PLAYLIST_URL = f"{HOST_URL}/get.php?username={USERNAME}&password={PASSWORD}&type=m3u_plus&output=ts"

OUTPUT_DIR = "Queen"
os.makedirs(OUTPUT_DIR, exist_ok=True)

output_live = os.path.join(OUTPUT_DIR, "Live.m3u")
output_movies = os.path.join(OUTPUT_DIR, "Movies.m3u")
output_series = os.path.join(OUTPUT_DIR, "Web Series.m3u")
output_tvshows = os.path.join(OUTPUT_DIR, "TV Shows.m3u")

if __name__ == "__main__":
    filter_and_split_playlist(
        PLAYLIST_URL,
        output_live,
        output_series,
        output_movies,
        output_tvshows
    )
