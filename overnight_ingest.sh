#!/bin/bash
# overnight_ingest.sh — run after midnight UTC when API quotas reset
# pulls multilingual articles for both case studies via World News API + API League
#
# usage: nohup bash overnight_ingest.sh > logs/overnight_ingest.log 2>&1 &

set -e
cd /storage/news
source /home/kiran/.bashrc

echo "=== OVERNIGHT INGESTION START: $(date -u) ==="
echo ""

# ── CS1 Iran: fill remaining languages (priority B) ──
# priority A already pulled: fr, de, es, it, ar, fa, hi, tr, ru, pt, ja, ko, zh, id, nl
echo "--- CS1 Iran: priority B languages ---"
for lang in he ur bn sw sv ro el cs hu th vi ms; do
    echo "  pulling $lang..."
    python3 worldnews_ingest.py cs1_iran --lang $lang 2>&1 | tail -5
    sleep 2
done

# ── CS2 Tariffs: all windows × priority A languages ──
echo ""
echo "--- CS2 Tariffs: priority A languages × all windows ---"
for lang in fr de es it ar fa hi tr ru pt ja ko zh; do
    for window in w1 w2 w3 w4 w5; do
        echo "  $lang / $window..."
        python3 worldnews_ingest.py cs2_tariffs --lang $lang --window $window 2>&1 | tail -3
        sleep 2
    done
done

# ── CS2 Tariffs: full pull (all languages, all windows) ──
echo ""
echo "--- CS2 Tariffs: full pull ---"
python3 worldnews_ingest.py cs2_tariffs 2>&1 | tail -30

# ── NewsData.io: current events supplement (CS1 Iran) ──
echo ""
echo "--- NewsData.io: CS1 Iran current coverage ---"
for lang in ar fa hi tr ru ja ko zh ur bn sw he; do
    echo "  $lang..."
    python3 newsdata_ingest.py cs1_iran --lang $lang 2>&1 | tail -3
    sleep 1
done

# ── archive.org backfill for CS2 pipeline failures ──
echo ""
echo "--- archive.org backfill for CS2 ---"
python3 archive_fetcher.py articles.json 2>&1 | tail -10

echo ""
echo "=== OVERNIGHT INGESTION COMPLETE: $(date -u) ==="
