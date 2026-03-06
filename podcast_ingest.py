#!/usr/bin/env python3
"""
podcast_ingest.py — tier 3 ingestion: podcast RSS → audio → transcript.

discovers podcasts via curated RSS feeds, downloads recent episodes about
Iran/strikes, transcribes via faster-whisper on boron.
output matches pipeline.py's articles.json schema.
"""

import json
import os
import re
import subprocess
import sys
import time
import hashlib
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

ARTICLES_FILE = "articles.json"
AUDIO_DIR = "sources/tier3/audio"
TRANSCRIPT_DIR = "sources/tier3/transcripts"
MAX_PER_PODCAST = 2
MAX_EPISODE_MINUTES = 60   # skip very long episodes
LOOKBACK_DAYS = 7
WHISPER_MODEL = "large-v3"

# curated podcast feeds — diverse geopolitical analysis sources
PODCAST_FEEDS = [
    {
        "name": "BBC World Service - Newshour",
        "rss": "https://podcasts.files.bbci.co.uk/p002vsmz.rss",
        "country": "United Kingdom", "language": "English", "region": "Europe",
    },
    {
        "name": "Al Jazeera - The Take",
        "rss": "https://feeds.buzzsprout.com/1107960.rss",
        "country": "Qatar", "language": "English", "region": "Middle East",
    },
    {
        "name": "Foreign Policy - The Negotiation",
        "rss": "https://feeds.megaphone.fm/FOPO2960564766",
        "country": "United States", "language": "English", "region": "North America",
    },
    {
        "name": "Council on Foreign Relations - The World Next Week",
        "rss": "https://feeds.cfr.org/cfr_podcasts",
        "country": "United States", "language": "English", "region": "North America",
    },
    {
        "name": "Chatham House - Undercurrents",
        "rss": "https://feeds.acast.com/public/shows/chathamhouse",
        "country": "United Kingdom", "language": "English", "region": "Europe",
    },
]

SEARCH_TERMS = ["iran", "tehran", "strike", "nuclear", "bombing", "missile", "middle east"]


def ensure_dirs():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)


def fetch_rss(url, timeout=15):
    """fetch and parse RSS feed."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "NewsKaleidoscope/0.1",
        "Accept": "application/rss+xml, application/xml, text/xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def parse_podcast_items(xml_text):
    """extract episodes from podcast RSS, including audio enclosure URLs."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pubdate = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()

        # get audio enclosure
        enclosure = item.find("enclosure")
        audio_url = ""
        if enclosure is not None:
            audio_url = enclosure.get("url", "")
            enc_type = enclosure.get("type", "")
            # only audio enclosures
            if enc_type and "audio" not in enc_type:
                audio_url = ""

        # also check for itunes:duration
        duration_text = ""
        for child in item:
            if "duration" in child.tag.lower():
                duration_text = (child.text or "").strip()

        if title and audio_url:
            items.append({
                "title": title,
                "url": link or audio_url,
                "audio_url": audio_url,
                "pubdate": pubdate,
                "description": desc[:300],
                "duration_text": duration_text,
            })

    return items


def parse_duration(duration_text):
    """parse podcast duration string to seconds. handles HH:MM:SS, MM:SS, seconds."""
    if not duration_text:
        return None
    # try HH:MM:SS or MM:SS
    parts = duration_text.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(duration_text)
    except ValueError:
        return None


def matches_event(item):
    """check if episode is relevant."""
    text = f"{item['title']} {item['description']}".lower()
    return any(term in text for term in SEARCH_TERMS)


def download_audio(audio_url, video_id):
    """download podcast audio from URL."""
    output_path = os.path.join(AUDIO_DIR, f"podcast_{video_id}.wav")
    if os.path.exists(output_path):
        return output_path

    # download to temp file, then convert to wav via ffmpeg
    temp_path = os.path.join(AUDIO_DIR, f"podcast_{video_id}_raw")
    try:
        req = urllib.request.Request(audio_url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(temp_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

        # convert to wav for whisper
        result = subprocess.run(
            ["ffmpeg", "-i", temp_path, "-ar", "16000", "-ac", "1", "-y", output_path],
            capture_output=True, timeout=120,
        )
        if os.path.exists(temp_path):
            os.remove(temp_path)

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
    except Exception:
        pass

    # cleanup
    for p in [temp_path, output_path]:
        if os.path.exists(p):
            os.remove(p)
    return None


def transcribe_on_boron(audio_path, language="en"):
    """transcribe audio using faster-whisper on boron."""
    transcript_hash = hashlib.md5(audio_path.encode()).hexdigest()
    transcript_path = os.path.join(TRANSCRIPT_DIR, f"{transcript_hash}.json")

    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # scp audio to boron (storage is NOT shared between machines)
    subprocess.run(["ssh", "boron", "mkdir", "-p", "/tmp/nk-whisper"],
                    capture_output=True, timeout=10)
    remote_audio = f"/tmp/nk-whisper/{os.path.basename(audio_path)}"
    scp = subprocess.run(["scp", "-q", audio_path, f"boron:{remote_audio}"],
                          capture_output=True, text=True, timeout=120)
    if scp.returncode != 0:
        print(f"scp failed: {scp.stderr[:100]}")
        return None

    lang_arg = f'"{language}"' if language != "auto" else "None"
    script = f'''import json
from faster_whisper import WhisperModel
model = WhisperModel("{WHISPER_MODEL}", device="cuda", compute_type="float16")
segments, info = model.transcribe("{remote_audio}", beam_size=5, language={lang_arg})
result = {{"language": info.language, "language_probability": info.language_probability, "duration": info.duration, "segments": []}}
full_text = []
for segment in segments:
    result["segments"].append({{"start": segment.start, "end": segment.end, "text": segment.text}})
    full_text.append(segment.text)
result["full_text"] = " ".join(full_text)
print(json.dumps(result))
'''
    subprocess.run(["ssh", "boron", "cat > /tmp/nk-whisper/_job.py"],
                    input=script, capture_output=True, text=True, timeout=10)

    try:
        proc = subprocess.run(
            ["ssh", "boron", "python3", "/tmp/nk-whisper/_job.py"],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            transcript = json.loads(proc.stdout.strip())
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump(transcript, f, indent=2, ensure_ascii=False)
            return transcript
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def main():
    ensure_dirs()

    existing_urls = set()
    existing_articles = []
    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing_articles = json.load(f)
        existing_urls = {a["url"] for a in existing_articles}
    except FileNotFoundError:
        pass

    print(f"[podcast] scanning {len(PODCAST_FEEDS)} podcast feeds...")

    new_articles = []
    stats = {"feeds_scanned": 0, "episodes_found": 0, "downloaded": 0,
             "transcribed": 0, "errors": 0}

    for feed in PODCAST_FEEDS:
        name = feed["name"]
        print(f"\n  {name}...", flush=True)
        stats["feeds_scanned"] += 1

        xml_text = fetch_rss(feed["rss"])
        if not xml_text:
            print(f"    FAILED to fetch RSS")
            stats["errors"] += 1
            continue

        items = parse_podcast_items(xml_text)
        relevant = [it for it in items if matches_event(it)]

        # filter by duration
        filtered = []
        for it in relevant:
            dur = parse_duration(it.get("duration_text", ""))
            if dur and dur > MAX_EPISODE_MINUTES * 60:
                continue
            filtered.append(it)

        relevant = filtered[:MAX_PER_PODCAST]

        if not relevant:
            print(f"    no relevant episodes")
            continue

        print(f"    found {len(relevant)} relevant episodes")
        stats["episodes_found"] += len(relevant)

        for ep in relevant:
            ep_url = ep["url"]
            if ep_url in existing_urls:
                continue

            ep_hash = hashlib.md5(ep["audio_url"].encode()).hexdigest()[:12]
            print(f"    downloading: {ep['title'][:50]}...", end=" ", flush=True)

            audio_path = download_audio(ep["audio_url"], ep_hash)
            if not audio_path:
                print("FAILED")
                stats["errors"] += 1
                continue
            stats["downloaded"] += 1

            whisper_lang = "en" if feed["language"] == "English" else "auto"
            print(f"transcribing...", end=" ", flush=True)

            transcript = transcribe_on_boron(audio_path, language=whisper_lang)
            if not transcript or not transcript.get("full_text"):
                print("FAILED")
                stats["errors"] += 1
                continue
            stats["transcribed"] += 1

            duration_min = transcript.get("duration", 0) / 60
            text_len = len(transcript.get("full_text", ""))
            print(f"ok ({duration_min:.1f}min, {text_len} chars)")

            existing_urls.add(ep_url)
            new_articles.append({
                "url": ep_url,
                "title": ep["title"],
                "seendate": ep.get("pubdate", ""),
                "sourcecountry": feed["country"],
                "sourcelang": transcript.get("language", feed["language"]),
                "domain": f"podcast/{name.replace(' ', '_')}",
                "source": "podcast_whisper",
                "tier": 3,
                "region": feed.get("region", "unknown"),
                "transcript_chars": text_len,
                "duration_minutes": round(duration_min, 1),
                "whisper_model": WHISPER_MODEL,
            })

            # cache transcript for pipeline
            url_hash = hashlib.md5(ep_url.encode()).hexdigest()
            cache_path = os.path.join("cache", f"{url_hash}.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(transcript["full_text"])

        time.sleep(1)  # politeness between feeds

    if new_articles:
        merged = existing_articles + new_articles
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"[podcast] SUMMARY")
    print(f"  feeds scanned: {stats['feeds_scanned']}")
    print(f"  relevant episodes: {stats['episodes_found']}")
    print(f"  downloaded: {stats['downloaded']}")
    print(f"  transcribed: {stats['transcribed']}")
    print(f"  errors: {stats['errors']}")
    print(f"  new articles added: {len(new_articles)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
