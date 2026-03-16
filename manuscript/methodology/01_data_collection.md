# Data Collection and Corpus Construction

## Overview

The NewsKaleidoscope corpus was assembled from three complementary data sources: the GDELT Global Knowledge Graph (Tier 1), the World News API (Tier 1), and Reddit's public API (Tier 3). Each source captures a distinct stratum of global discourse: GDELT provides broad multilingual institutional media coverage, the World News API supplements with full-text articles from underrepresented language communities, and Reddit captures vernacular online discourse as articulated by non-professional commentators. Three case studies were constructed using this infrastructure: CS1 (US-Israeli strikes on Iran, February 26 -- March 6, 2026; 1,267 articles, 24 languages, 330 sources), CS2 (US reciprocal tariffs, April 2025 -- March 2026; 1,496 articles, 31 languages, 622 sources), and CS1-RU (Russian invasion of Ukraine, February 24 -- March 2, 2022; 2,096 articles, 41 languages, 717 sources).

## GDELT DOC API (Primary Source)

The GDELT Project's DOC 2.0 API served as the primary ingestion pathway. GDELT continuously monitors news media worldwide, indexing article metadata including URL, title, publication timestamp, source country, and detected language. The API's `artlist` mode was used to retrieve article pools for each case study.

### Query Strategy

For each case study, multiple query terms were submitted to maximize recall across framing perspectives. For CS1 (Iran), queries included both neutral descriptors ("Iran strike attack") and terms capturing distinct framing orientations. For CS1-RU (Ukraine), eight queries were used (see `cs1ru_ingest.py`), deliberately spanning the range from Western framing ("Ukraine aggression sovereignty") to Russian state framing ("special military operation Ukraine") to humanitarian angles ("Ukraine refugees humanitarian crisis") to geopolitical framing ("NATO Ukraine Russia sanctions"). This multi-query strategy ensured that GDELT's relevance-ranked results did not systematically exclude articles whose framing deviated from any single perspective.

Query parameters were configured as follows: `mode=artlist`, `maxrecords=250` per query, `format=json`, with date windows set to 7-day periods matching the event's acute phase. For CS1-RU, the `startdatetime` and `enddatetime` parameters targeted the GDELT historical archive (February 24 -- March 2, 2022).

### Rate Limiting and Fallback

GDELT enforces aggressive rate limits. The ingestion pipeline implemented exponential backoff with 3 retries per request, with wait times of 15, 30, and 45 seconds upon receiving HTTP 429 responses or non-JSON rate-limit pages. An 8-second inter-request delay was used for CS1-RU (`cs1ru_ingest.py`, `REQUEST_DELAY = 8`). When the primary machine (nitrogen) was rate-limited, the pipeline automatically fell back to fetching via a second machine (boron) over SSH, exploiting the different IP address to bypass per-IP rate limits (see `fetch_via_boron()` in `gdelt_pull.py`, `cs1ru_ingest.py`).

### Geographic Diversity Enforcement

Raw GDELT pools are dominated by high-volume English-language media producers. To prevent this bias from collapsing the corpus into a narrow set of perspectives, a round-robin geographic diversity algorithm was applied. Rather than first-come-first-served selection (which favors countries with higher media output), the algorithm iterates across all represented countries, taking one article per country per round, up to a configurable maximum per country (`MAX_PER_COUNTRY`). For CS1, this was set to 3 articles per country with a target of 60 total. For CS1-RU, the cap was raised to 5 per country with a target of 300, reflecting the event's larger scale of global coverage. In a later corpus expansion (session 13), the geographic diversity cap was removed entirely for CS1-RU to maximize corpus size, yielding 1,944 GDELT articles.

The round-robin algorithm is implemented in `enforce_geo_diversity()`:

```
for each round (up to MAX_PER_COUNTRY):
    for each country (sorted alphabetically):
        if country has remaining articles AND under cap:
            select one article
```

This ensures that a country with 200 articles in the pool receives the same representation as one with 5, preventing the corpus from being dominated by a small number of high-output media ecosystems.

## World News API (Supplementary Source)

The World News API (worldnewsapi.com) was used as a supplementary ingestion source, with its primary advantage being the return of full article text in API responses -- eliminating the need for separate text extraction. The API supports 80+ languages and 210+ countries, with historical query capabilities.

### Multilingual Query Architecture

For each case study, search queries were formulated in the target language rather than relying on English-only queries. Language-specific queries were organized into two priority tiers based on gap severity in the GDELT corpus (`worldnews_ingest.py`):

- **Tier A** (10 languages): French, German, Spanish, Italian, Arabic, Persian, Hindi, Turkish, Russian, Portuguese -- representing the largest representation gaps.
- **Tier B** (18 languages): Japanese, Korean, Chinese, Indonesian, Dutch, Polish, Hebrew, Urdu, Bengali, Swahili, Swedish, Romanian, Greek, Czech, Hungarian, Thai, Vietnamese, Malay.

For CS1 (Iran), queries were localized into 16 language variants (e.g., Arabic: "hujum iran", "darba iran"; Persian: "hamla iran", "bambarun iran"; Turkish: "Iran saldiri"; Hindi: "Iran hamla"). For CS1-RU (Ukraine), 22 language variants were used, including Ukrainian ("Rossia Ukraina vtorhennia").

### API Failover

Two API endpoints with separate quotas were configured (`api.worldnewsapi.com` and `api.apileague.com`), with automatic failover when quota was exhausted (HTTP 402). The `X-API-Quota-Left` response header was monitored to trigger preemptive endpoint switching below 5 remaining requests.

### Limitations for Historical Events

The World News API returned zero results for the 2022 Ukraine event window across all 28 queried languages, despite supporting date-range parameters. This API limitation was discovered during CS1-RU corpus construction and is documented as a methodological constraint: the API does not maintain historical article archives for dates prior to its operational period.

## Reddit (Vernacular Discourse)

Reddit was used to capture how non-professional commentators frame geopolitical events in informal discussion. This source is explicitly labeled as "vernacular online discourse" rather than public opinion, as Reddit's demographic skew (English-dominant, younger, more male, more Western) is well-documented.

### Subreddit Selection

For each case study, subreddits were selected to represent both global discussion spaces and country-specific communities (`reddit_ingest.py`):

- **Global geopolitical**: r/worldnews, r/geopolitics
- **Directly involved parties**: For CS1-RU, r/ukraine, r/russia, r/AskARussian, r/liberta (Russian-language opposition)
- **Regional perspectives**: r/europe, r/de (Germany), r/france, r/Polska (Poland), r/india, r/China_irl, r/brasil
- **Conflict-specific**: For CS1-RU, r/UkrainianConflict, r/CombatFootage

CS1 used 17 subreddits; CS1-RU used 21 subreddits; CS2 (tariffs) used 25 subreddits, including economics-focused communities and subreddits for countries most affected by trade policy (r/VietNam, r/Philippines, r/bangladesh).

### Data Capture

Reddit's public JSON API was accessed without authentication. For each subreddit, up to 5 search queries were executed with `sort=relevance` and `limit=25`. Posts were filtered by creation timestamp to the event window (e.g., February 22 -- March 5, 2022 for CS1-RU) and by minimum engagement (`score >= 2`) to exclude spam. The top 10 posts per subreddit (ranked by score) were retained, and for each, up to 5 top-level comments were fetched. Comments marked `[deleted]` or `[removed]` or shorter than 20 characters were excluded; surviving comments were capped at 2,000 characters.

The captured text for each Reddit "article" was composed as: post title + self-text (capped at 3,000 characters) + top comments (prefixed with score). This composite text was cached using the same MD5 URL-hash scheme as traditional articles, allowing it to pass through the same pipeline.

Rate limiting respected Reddit's guidelines: a 2.5-second delay between requests, with exponential backoff (10, 20, 30 seconds) on HTTP 429 responses.

### Corpus Contribution

For CS1-RU, Reddit contributed 152 articles to the total corpus of 2,096 (7.2%). Each Reddit article was tagged with metadata including subreddit, region, language, engagement score, and comment count, enabling downstream analysis to distinguish vernacular from institutional framing.

## Wayback Machine Recovery (CS1-RU)

For the Ukraine 2022 case study (CS1-RU), many original article URLs from four years prior were no longer accessible. A three-tier text extraction strategy was employed (see `scripts/fetch_text_cs1ru.py`): trafilatura (preferred) to newspaper3k (fallback) to the Internet Archive's Wayback Machine (final fallback). The Wayback Machine was accessed via an `archive_fetcher` module that queried the Wayback CDX API for archived snapshots and extracted text from the archived HTML.

This recovery strategy achieved an overall text extraction success rate of 86.2% (1,456 out of 1,689 articles requiring extraction). The Wayback Machine was the decisive factor for articles whose original domains had gone offline or restructured since 2022.

## Deduplication

Deduplication was enforced at two levels. During ingestion, each script maintained an in-memory set of seen URLs and rejected duplicates within a single run. At the database level, the `articles` table enforced a `UNIQUE` constraint on the `url` column (`articles_url_key`), preventing duplicate insertion across runs and data sources. The `cs1ru_ingest.py` script explicitly checked `SELECT id FROM articles WHERE url = %s` before each insert, skipping known URLs and reporting the count of duplicates encountered.

## Final Corpus Statistics

| Case Study | Event | Date Window | Total Articles | GDELT | Reddit | Languages | Sources |
|---|---|---|---|---|---|---|---|
| CS1 | US-Israeli strikes on Iran | Feb 26 -- Mar 6, 2026 | 1,267 | ~1,267 | -- | 24 | 330 |
| CS2 | US reciprocal tariffs | Apr 2025 -- Mar 2026 | 1,496 | ~1,496 | -- | 31 | 622 |
| CS1-RU | Russian invasion of Ukraine | Feb 24 -- Mar 2, 2022 | 2,096 | 1,944 | 152 | 41 | 717 |

All article metadata and text were stored in a PostgreSQL database (`newskaleidoscope`). The `articles` table recorded event association, source linkage, original language, raw text, translated text, publication date, and ingestion timestamp. Raw article text was additionally cached to the filesystem by MD5 hash of the URL, providing a filesystem-level backup independent of the database.
