#!/usr/bin/env python3
"""
youtube_ingest.py — tier 3 ingestion: YouTube → audio → transcript via Whisper.

uses yt-dlp to download audio from curated YouTube channels, then
faster-whisper on boron's TITAN RTX GPUs to transcribe.
output format matches pipeline.py's articles.json schema so transcripts
feed directly into the two-pass framing analysis.

architecture:
  nitrogen: orchestrates downloads, manages article list
  boron: GPU transcription via faster-whisper (runs as subprocess via ssh)
"""

import json
import os
import re
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timedelta

ARTICLES_FILE = "articles.json"
SOURCES_DIR = "sources/tier3"
AUDIO_DIR = "sources/tier3/audio"
TRANSCRIPT_DIR = "sources/tier3/transcripts"
MAX_PER_CHANNEL = 3        # cap per channel for corpus balance
MAX_VIDEO_MINUTES = 30     # skip anything longer (lectures, live streams)
LOOKBACK_DAYS = 7          # how far back to search
WHISPER_MODEL = "large-v3" # best accuracy; ~4GB VRAM

# seed channels — curated for geographic/ideological diversity on Iran coverage
# format: {"id": "channel_id_or_handle", "name": "display name", "country": "...", "language": "..."}
SEED_CHANNELS = [
    # middle east
    {"id": "@AlJazeeraEnglish", "name": "Al Jazeera English", "country": "Qatar", "language": "English", "region": "Middle East"},
    {"id": "@taborabdulhak", "name": "TRT World", "country": "Turkey", "language": "English", "region": "Middle East"},
    {"id": "@PressTV", "name": "Press TV (Iran)", "country": "Iran", "language": "English", "region": "Middle East"},
    # south/east asia
    {"id": "@WIONews", "name": "WION", "country": "India", "language": "English", "region": "South Asia"},
    {"id": "@CGTNOfficial", "name": "CGTN", "country": "China", "language": "English", "region": "East Asia"},
    # africa/global south
    {"id": "@afriaborgen", "name": "Africa News", "country": "France/Africa", "language": "English", "region": "Africa"},
    # western
    {"id": "@BBCNews", "name": "BBC News", "country": "United Kingdom", "language": "English", "region": "Europe"},
    {"id": "@DWNews", "name": "DW News", "country": "Germany", "language": "English", "region": "Europe"},
]

# search terms for filtering relevant videos
SEARCH_TERMS = ["iran", "tehran", "strike", "nuclear", "bombing", "missile", "isfahan", "natanz"]


def ensure_dirs():
    """create output directories."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)


def find_channel_videos(channel_id, lookback_days=LOOKBACK_DAYS):
    """use yt-dlp to list recent videos from a channel, filtered by relevance."""
    # date filter: only videos from the last N days
    date_after = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(upload_date)s\t%(duration)s",
        "--dateafter", date_after,
        "--playlist-end", "30",  # scan last 30 uploads, filter by relevance
        f"https://www.youtube.com/{channel_id}/videos",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        vid_id, title, upload_date, duration = parts[0], parts[1], parts[2], parts[3]

        # filter: must match search terms
        title_lower = title.lower()
        if not any(term in title_lower for term in SEARCH_TERMS):
            continue

        # filter: skip long videos
        try:
            dur_sec = int(duration) if duration != "NA" else 0
            if dur_sec > MAX_VIDEO_MINUTES * 60:
                continue
        except ValueError:
            pass

        videos.append({
            "id": vid_id,
            "title": title,
            "upload_date": upload_date,
            "duration_sec": dur_sec if duration != "NA" else None,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
        })

    return videos


def download_audio(video_id, output_dir=AUDIO_DIR):
    """download audio-only from a youtube video."""
    output_path = os.path.join(output_dir, f"{video_id}.wav")

    # skip if already downloaded
    if os.path.exists(output_path):
        return output_path

    cmd = [
        "yt-dlp",
        "-x",                          # extract audio
        "--audio-format", "wav",        # wav for whisper compatibility
        "--audio-quality", "0",         # best quality
        "-o", output_path,
        f"https://www.youtube.com/watch?v={video_id}",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        # yt-dlp sometimes adds .wav.wav — check for that
        alt_path = output_path + ".wav"
        if os.path.exists(alt_path):
            os.rename(alt_path, output_path)
            return output_path
    except subprocess.TimeoutExpired:
        pass

    return None


def transcribe_on_boron(audio_path, language="en"):
    """transcribe audio using faster-whisper on boron via ssh.

    sends a python snippet to boron that loads faster-whisper,
    transcribes the audio file (accessible via shared /storage),
    and returns the transcript as JSON.
    """
    # the audio file is on shared storage, so boron can access it directly
    transcript_hash = hashlib.md5(audio_path.encode()).hexdigest()
    transcript_path = os.path.join(TRANSCRIPT_DIR, f"{transcript_hash}.json")

    # skip if already transcribed
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # build python script for boron to execute
    # uses faster-whisper with GPU acceleration
    py_script = f'''
import json
from faster_whisper import WhisperModel

model = WhisperModel("{WHISPER_MODEL}", device="cuda", compute_type="float16")
segments, info = model.transcribe("{audio_path}", beam_size=5, language="{language}" if "{language}" != "auto" else None)

result = {{
    "language": info.language,
    "language_probability": info.language_probability,
    "duration": info.duration,
    "segments": []
}}

full_text = []
for segment in segments:
    result["segments"].append({{
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
    }})
    full_text.append(segment.text)

result["full_text"] = " ".join(full_text)
print(json.dumps(result))
'''

    try:
        proc = subprocess.run(
            ["ssh", "boron", "python3", "-c", py_script],
            capture_output=True, text=True, timeout=600,  # 10 min max
        )
        if proc.returncode == 0 and proc.stdout.strip():
            transcript = json.loads(proc.stdout.strip())
            # cache transcript
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(transcript, f, indent=2, ensure_ascii=False)
            return transcript
        else:
            print(f"    transcription error: {proc.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"    transcription timed out (>10min)")
    except json.JSONDecodeError:
        print(f"    invalid JSON from transcription")

    return None


def main():
    ensure_dirs()

    # load existing articles to avoid duplicates
    existing_urls = set()
    existing_articles = []
    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing_articles = json.load(f)
        existing_urls = {a["url"] for a in existing_articles}
    except FileNotFoundError:
        pass

    print(f"[youtube] scanning {len(SEED_CHANNELS)} channels...")
    print(f"[youtube] lookback: {LOOKBACK_DAYS} days, max {MAX_PER_CHANNEL}/channel")

    new_articles = []
    stats = {"channels_scanned": 0, "videos_found": 0, "downloaded": 0,
             "transcribed": 0, "errors": 0, "skipped_duplicate": 0}

    for channel in SEED_CHANNELS:
        name = channel["name"]
        cid = channel["id"]
        country = channel["country"]
        language = channel["language"]
        region = channel.get("region", "unknown")

        print(f"\n  {name} ({cid})...", flush=True)
        stats["channels_scanned"] += 1

        # step 1: find relevant videos
        videos = find_channel_videos(cid)
        if not videos:
            print(f"    no relevant videos found")
            continue

        print(f"    found {len(videos)} relevant videos")
        stats["videos_found"] += len(videos)

        # cap per channel
        videos = videos[:MAX_PER_CHANNEL]

        for video in videos:
            vid_url = video["url"]
            if vid_url in existing_urls:
                print(f"    skip (duplicate): {video['title'][:50]}")
                stats["skipped_duplicate"] += 1
                continue

            print(f"    downloading: {video['title'][:50]}...", end=" ", flush=True)

            # step 2: download audio
            audio_path = download_audio(video["id"])
            if not audio_path:
                print("FAILED (download)")
                stats["errors"] += 1
                continue
            stats["downloaded"] += 1
            print("ok.", end=" ", flush=True)

            # step 3: transcribe on boron
            # detect language for whisper — use "auto" for non-English channels
            whisper_lang = "en" if language == "English" else "auto"
            print(f"transcribing ({whisper_lang})...", end=" ", flush=True)

            transcript = transcribe_on_boron(audio_path, language=whisper_lang)
            if not transcript or not transcript.get("full_text"):
                print("FAILED (transcription)")
                stats["errors"] += 1
                continue
            stats["transcribed"] += 1

            detected_lang = transcript.get("language", language)
            duration_min = transcript.get("duration", 0) / 60
            text_len = len(transcript.get("full_text", ""))
            print(f"ok ({detected_lang}, {duration_min:.1f}min, {text_len} chars)")

            # step 4: build article entry matching pipeline schema
            existing_urls.add(vid_url)
            new_articles.append({
                "url": vid_url,
                "title": video["title"],
                "seendate": video.get("upload_date", ""),
                "sourcecountry": country,
                "sourcelang": detected_lang,
                "domain": f"youtube.com/{cid}",
                "source": "youtube_whisper",  # flag tier 3 source
                "tier": 3,
                "region": region,
                "transcript_chars": text_len,
                "duration_minutes": round(duration_min, 1),
                "whisper_model": WHISPER_MODEL,
                "whisper_language_confidence": transcript.get("language_probability", 0),
            })

            # save transcript text to cache for pipeline.py to pick up
            # (uses same URL-hash cache as article text)
            url_hash = hashlib.md5(vid_url.encode()).hexdigest()
            cache_path = os.path.join("cache", f"{url_hash}.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(transcript["full_text"])

    # merge new articles into articles.json
    if new_articles:
        merged = existing_articles + new_articles
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

    # summary
    print(f"\n{'='*60}")
    print(f"[youtube] SUMMARY")
    print(f"  channels scanned: {stats['channels_scanned']}")
    print(f"  relevant videos found: {stats['videos_found']}")
    print(f"  downloaded: {stats['downloaded']}")
    print(f"  transcribed: {stats['transcribed']}")
    print(f"  skipped (duplicate): {stats['skipped_duplicate']}")
    print(f"  errors: {stats['errors']}")
    print(f"  new articles added: {len(new_articles)}")
    print(f"  total corpus now: {len(existing_articles) + len(new_articles)}")

    if new_articles:
        print(f"\n  new transcripts from:")
        for a in new_articles:
            print(f"    {a['domain']:35s} {a['sourcelang']:6s} {a['duration_minutes']:5.1f}m  {a['title'][:40]}")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
