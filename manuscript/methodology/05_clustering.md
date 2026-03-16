# Pass 2: Emergent Clustering

## Overview

After all articles in a case study were individually analyzed in Pass 1, a corpus-level clustering step (Pass 2) grouped the resulting framing descriptions into emergent categories. This clustering was performed by the same LLM used for Pass 1 analysis, operating on the full set of per-article summaries rather than on individual article texts. The design principle was that the taxonomy of framing patterns should emerge from the data itself, not be imposed by the analyst or by predefined codebooks.

## Why LLM Clustering Rather Than Embedding Clustering

A natural alternative to LLM-based clustering would be to embed all framing descriptions using a sentence-transformer model and apply standard unsupervised clustering algorithms (e.g., k-means, HDBSCAN, agglomerative clustering). This approach was attempted early in the project and produced a "mega-cluster failure" -- embedding-based methods collapsed semantically distinct framings into a small number of large clusters, because the sentence embeddings captured surface-level topical similarity (all articles discuss the same event) rather than the deeper structural differences in framing logic (who is granted authority, what is assumed, what is absent).

LLM-based clustering was chosen because the model can attend to the *argumentative structure* of framing descriptions rather than merely their lexical similarity. When the LLM reads that one article "treats the strike as a justified response to nuclear proliferation" and another "treats the strike as imperialist aggression in the tradition of 1953," it can recognize these as structurally opposed framings even though they share many surface-level words (strike, Iran, nuclear, military). Embedding-based methods would place these descriptions relatively close in vector space.

Both approaches are valid for different analytical purposes. Embedding clustering measures topical similarity; LLM clustering measures argumentative or epistemic similarity. The choice of LLM clustering is consistent with the project's goal of mapping *epistemic positions* rather than topics.

The embedding-based mega-cluster failure is preserved in the analysis record as part of the methodological paper's documentation of "what we tried and why it failed," consistent with the project's immutability rules.

## The Pass 2 Prompt

The clustering prompt (`PASS2_CLUSTER_PROMPT` in `pipeline.py`) received the complete set of article framing descriptions and instructed the LLM to:

1. Identify emergent clusters -- the natural groupings arising from the data.
2. Name each cluster with a descriptive phrase (not a single word), using the data's own language rather than political science textbook terms.
3. Note whether each cluster's members are geographically concentrated or dispersed.
4. Identify whether any cluster maps to a conventional political category, and if so, name it -- but allow clusters that resist conventional categorization.
5. Preserve singletons: articles that genuinely resist clustering were flagged as such, with an explanation of what makes their framing distinct. These singletons "may be the most interesting finding."

The prompt explicitly stated: "Do NOT start with predefined categories. Let the clusters emerge from the descriptions."

For each article, the input was formatted as: `[index] domain (country): one_sentence_summary`. When the `one_sentence_summary` field was unavailable, the `framing_description` was used, truncated to 300 characters.

The output JSON structure contained:

- `emergent_clusters`: array of objects with `cluster_name`, `description`, `member_indices`, `geographic_pattern`, and `maps_to_conventional_category` (nullable)
- `singletons`: array of objects with `index` and `why_unique`
- `meta_observation`: one paragraph on what the clustering reveals about global framing patterns

The LLM timeout for Pass 2 was extended to 300 seconds (compared to 180 for Pass 1), reflecting the larger prompt size and more complex reasoning required.

## Chunked Hierarchical Clustering

For large corpora (CS1 with 1,267 articles, CS1-RU with 1,863), the complete set of article descriptions exceeded the LLM's effective context window. A chunked hierarchical clustering approach was implemented in `scripts/recluster_chunked.py` to address this constraint.

### Algorithm

The procedure operates in multiple stages:

**Stage 1 (Initial chunking):** The full set of article summaries is divided into chunks of configurable size (default 80 articles). Each chunk is independently clustered using the standard Pass 2 prompt. The output for each chunk is a set of micro-clusters: named groups with member indices and descriptions.

**Stage 2+ (Hierarchical reduction):** The micro-clusters from Stage 1 are themselves treated as "pseudo-articles" -- each micro-cluster's summary becomes an input to a new clustering call. If the number of micro-clusters exceeds a configurable limit (default 120), they are chunked again (default chunks of 60) and the process repeats. Up to 4 levels of hierarchical reduction are permitted.

**Final merge:** Once the number of items falls below the final limit, a single Pass 2 clustering call attempts to produce the definitive cluster set. If this final call fails (e.g., context window still exceeded), the reduced items from the previous level are used directly.

### Recursive Fallback

The `cluster_items_recursive()` function implements a binary-split fallback: if a chunked clustering call fails (returns a raw unparseable response), the chunk is split in half and each half is clustered independently. This ensures that even if individual LLM calls fail, the overall process degrades gracefully rather than halting.

### Singleton Handling

Articles that the LLM places in singleton status at any level of the hierarchy are preserved through all reduction stages. Singletons at higher levels may represent genuinely unique framings or may be artifacts of the chunking process; the final output distinguishes between clusters (2+ members) and singletons (1 member).

### Database Storage

Cluster results were written to the `clusters` table with fields for `event_id`, `label` (cluster name), `article_count`, `geographic_signature` (JSONB), `description`, `maps_to_conventional` category, `is_singleton` (boolean), `run_id` (timestamped identifier), and `method` (set to `llm_pass2_chunked_hierarchical`). Cluster membership was recorded in the `cluster_memberships` table linking `cluster_id` to `article_id`.

Consistent with the project's immutability rules, new clustering runs produced new rows with distinct `run_id` values. Previous cluster data was never overwritten or deleted. The `valid` column (default `true`) allows soft deprecation of superseded results.

## Corpus-Level Absence Report

After clustering, a meta-analysis step identified structurally absent positions -- perspectives, actors, and framings that are missing from the corpus not by accident but by the structural properties of global media. The `ABSENCE_PROMPT` in `pipeline.py` received the cluster summary, country list, and language list, and was instructed to identify:

1. **Unrepresented actors**: Actors with obvious stakes but no voice in the corpus.
2. **Unmade arguments**: Legitimate arguments that no article makes.
3. **Voiceless populations**: Affected populations with no representation.
4. **Tier 3 predictions**: Framings that would likely appear from non-digital sources (oral media, WhatsApp networks, sermons, radio).
5. **Unspeakable positions**: Positions that are logically coherent but politically impossible to publish in any major outlet.

The absence report was stored as a JSON artifact in the `analysis/` directory, versioned by run_id.
