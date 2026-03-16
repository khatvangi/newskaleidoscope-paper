# Pass 2: Emergent Clustering Prompt

Source: `pipeline.py` (PASS2_CLUSTER_PROMPT, line 382)

Used by both `pipeline.py:pass2_cluster()` and `scripts/recluster_chunked.py` (which imports `pass2_cluster` from pipeline.py).

## Template Variables

- `{n}` — number of articles in the batch
- `{n_countries}` — number of distinct source countries
- `{event_context}` — from `events.prompt_context` DB field
- `{descriptions}` — formatted list of per-article summaries, one per line, format: `[index] domain (country): one_sentence_summary`

## Exact Prompt Text

```
You have analyzed {n} news articles from {n_countries} countries about {event_context}.

Below are the framing descriptions from each article. Your task: identify the EMERGENT clusters — the natural groupings that arise from the data itself.

RULES:
- Do NOT start with predefined categories. Let the clusters emerge from the descriptions.
- Some clusters may resemble expected categories (e.g., endorsement, opposition). That's fine — but name them in the data's own language, not political science textbook terms.
- Some articles may belong to multiple clusters. That's fine.
- If an article genuinely resists clustering, flag it as a singleton — it may be the most interesting finding.
- Name each cluster with a descriptive phrase, not a single word.
- For each cluster, note whether its members are geographically concentrated or dispersed.

ARTICLE DESCRIPTIONS:
{descriptions}

Output JSON:
{
  "emergent_clusters": [
    {
      "cluster_name": "descriptive name for this framing pattern",
      "description": "what unites these articles — the shared assumptions, vocabulary, or framing logic",
      "member_indices": [0, 3, 7],
      "geographic_pattern": "concentrated in X region / dispersed globally / etc.",
      "maps_to_conventional_category": "if this resembles a standard political category, name it. otherwise null"
    }
  ],
  "singletons": [
    {
      "index": 5,
      "why_unique": "what makes this article's framing distinct from all clusters"
    }
  ],
  "meta_observation": "one paragraph on what the clustering reveals about global framing patterns that would not be visible from any single article or region"
}

IMPORTANT: Output ONLY valid JSON, no other text.
```

## LLM Call Parameters (Clustering)

- `temperature`: 0.3
- `max_tokens`: 3072
- `timeout`: 300 seconds (extended for corpus-level reasoning)

## Hierarchical Chunked Clustering (recluster_chunked.py)

For large corpora that exceed the LLM context window, `recluster_chunked.py` implements multi-level hierarchical clustering:

1. **Stage 1**: Articles split into chunks of 80 (configurable `--chunk-size`). Each chunk is clustered via `pass2_cluster()`.
2. **Reduction passes**: If output exceeds `--final-limit` (default 120), micro-clusters are re-chunked (60 per batch) and re-clustered recursively, up to `--max-levels` (default 4) levels.
3. **Final merge**: A single `pass2_cluster()` call on the reduced set produces the final cluster structure.

At each level, article summaries are condensed into micro-cluster summaries (max 240 chars), and the same `PASS2_CLUSTER_PROMPT` is reused with pseudo-results constructed from micro-cluster descriptions.

## Corpus-Level Absence Report Prompt

Source: `pipeline.py` (ABSENCE_PROMPT, line 451)

Runs once after clustering to identify structurally missing perspectives.

### Template Variables

- `{n}`, `{n_countries}` — corpus size
- `{event_context}` — event description
- `{country_list}` — comma-separated list of source countries
- `{lang_list}` — comma-separated list of source languages
- `{cluster_summary}` — formatted list of cluster names and descriptions
- `{absence_examples}` — from `events.absence_examples` DB field (e.g., "underrepresented domestic media, marginalized communities")

### Exact Prompt Text

```
You have analyzed {n} news articles from {n_countries} countries about {event_context}.

The articles came from these countries: {country_list}
The languages represented: {lang_list}

Here is a summary of the framing positions found:
{cluster_summary}

Now identify what is STRUCTURALLY ABSENT from this corpus:

1. Which actors have obvious stakes in this event but are NOT represented? (e.g., {absence_examples})
2. What arguments could legitimately be made about this event that NO article in this set makes?
3. Which regions or populations are affected by this event but have no voice in this corpus?
4. What framings would appear if the corpus included Tier 3 sources — oral media, WhatsApp networks, sermons, radio?
5. Are there positions that are logically possible but politically unspeakable in any major outlet?

Output JSON:
{
  "unrepresented_actors": ["actors with stakes but no voice in this corpus"],
  "unmade_arguments": ["legitimate arguments that no article makes"],
  "voiceless_populations": ["affected populations with no representation"],
  "tier3_predictions": ["framings that would likely appear from non-digital sources"],
  "unspeakable_positions": ["positions that are logically coherent but politically impossible to publish"],
  "overall_assessment": "one paragraph on what this corpus's absences reveal about the structure of global media"
}

IMPORTANT: Output ONLY valid JSON, no other text.
```

### LLM Call Parameters (Absence Report)

- `temperature`: 0.3
- `max_tokens`: 3072
- `timeout`: 300 seconds
