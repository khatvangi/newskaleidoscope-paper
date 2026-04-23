# Epstein Intellectual Corruption — New Session Guide

## Start Here
Read `/home/kiran/.claude/projects/-storage-news/memory/project_epstein_intellectuals.md` for full context.

## Current State (as of Mar 22, 2026)

### Active Jobs — CHECK FIRST
1. **Entity context extraction** running on boron (qwen3-32b, port 11434)
   - `tail -5 logs/entity_context_event6.log`
   - Check: `python3 scripts/entity_context_extractor.py --status --event-id 6`
   - **KILL when done**: `ssh boron "pkill llama-server"`

2. **Main Epstein Pass 1** running on nitrogen (Mistral-24B, port 11436)
   - Check: `PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope -c "SELECT COUNT(*) FROM analyses WHERE event_id = 5;"`
   - Target: 4,164 articles
   - **KILL when done**: `pkill llama-server`

### DB State
- **event_id=5** (Epstein Global): 6,167 articles, 4,164 with text, Pass 1 at ~3,570/4,164
- **event_id=6** (Intellectual): 801 articles, 362 with text+translated+Pass1, entity extraction running
- **epstein_entities table**: 106 entities (96 API + 42 known + 23 intellectuals)
- **epstein_entity_contexts table**: being populated by entity_context_extractor.py

### What Needs Doing (in order)

1. **Check entity extraction completion** on boron, kill llama-server
2. **Extract + translate new 439 articles** (event_id=6 expanded from 396 to 801)
   ```bash
   python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --phase extract
   python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --phase translate
   ```
3. **Run Pass 1 on new articles** (event_id=6, the 439 new ones)
   ```bash
   python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --phase analyze
   ```
4. **Run entity context extraction on ALL articles** (not just original 362)
   ```bash
   python3 scripts/entity_context_extractor.py --event-id 6 --llm-url http://boron:11434
   # also run on main corpus intellectual articles:
   python3 scripts/entity_context_extractor.py --event-id 5 --llm-url http://boron:11434
   ```
5. **Run suppression index comparison**
   ```bash
   python3 scripts/epstein_primary_docs.py compare
   ```
6. **Council + clustering** on event_id=6
7. **Generate "Academic Reckoning" report** in CfMM editorial style

### Key Scripts
- `scripts/entity_context_extractor.py` — deep per-entity involvement extraction
- `scripts/epstein_intellectuals.py` — entity DB + article tagging + suppression index
- `scripts/epstein_primary_docs.py` — primary doc references from Investigation API
- `scripts/topic_runner.py` — generic pipeline orchestrator
- `topics/epstein-intellectual-corruption-v2.yaml` — expanded topic config (37 queries)

### Key Findings So Far
- **Suppressed names** (in docs but 0 media): Danny Hillis, Seth Lloyd, Gell-Mann, Sacks, Strominger
- **Amplified names** (over-covered vs docs): Chomsky 8.5x, Summers 8.2x, Hawking 2.0x
- **Pattern**: media covers celebrity intellectuals, suppresses working scientists who quietly took money
- **Entity context extraction** extracting graduated involvement: name_drop → received_funding → deep_complicity
- **First results**: Joi Ito tagged as both `received_funding` AND `deep_complicity` from different articles

### The Five Reports (from parent project)
1. How the World Frames the Epstein Files (event_id=5, emergent clustering)
2. **The Suppression Index** (primary docs vs media)
3. **The Academic Reckoning** ← THIS SESSION'S FOCUS (event_id=6)
4. The Transatlantic Divide (US vs UK vs Israel vs France)
5. Who Protects Whom (outlet ownership vs name suppression)

### 23 Intellectual Entities Being Tracked

| Name | Type | Institution | Doc Mentions | Key Detail |
|------|------|-------------|-------------|------------|
| Deepak Chopra | spiritual_guru | Chopra Foundation | 3500+ raw | "cute girls" emails, $50K |
| Joi Ito | tech_academic | MIT Media Lab | 40 | $850K to Lab, $1.7M personal, resigned twice |
| Lawrence Summers | academic_leader | Harvard | 30 | donations after becoming president |
| Marvin Minsky | scientist | MIT | 25 | alleged victim interaction |
| Steven Pinker | scientist | Harvard | 20 | flight logs, legal opinion |
| Martin Nowak | scientist | Harvard | 20 | paid leave Feb 2026 |
| Noam Chomsky | intellectual | MIT/Arizona | 15 | $270K moved through account |
| Danny Hillis | tech_academic | MIT/Applied Minds | 15 | long-time associate, **0 media coverage** |
| George Church | scientist | Harvard/MIT | 15 | genomics projects |
| Peter Attia | doctor | longevity medicine | 15 | relationship exposed |
| Seth Lloyd | scientist | MIT | 10 | $225K, **0 media coverage** |
| David Gelernter | scientist | Yale | 10 | suspended from teaching |
| Dean Ornish | doctor | UCSF | 10 | associate |
| Richard Axel | scientist | Columbia | 10 | Nobel laureate, stepped down |
| Stephen Hawking | scientist | Cambridge | 10 | 2006 conference, photographed on island |
| Nathan Myhrvold | tech_academic | Microsoft/IV | 8 | attended events |
| Nicholas Christakis | scientist | Yale | 8 | met 2013, corresponded 2013-16 |
| Lisa Randall | scientist | Harvard | 8 | correspondence in files |
| Leon Botstein | academic_leader | Bard College | 8 | $150K to college |
| Murray Gell-Mann | scientist | Caltech/SFI | 5 | Nobel physicist, dinners |
| Andrew Strominger | scientist | Harvard | 5 | correspondence |
| Elisa New | academic | Harvard | 5 | Summers' partner |
| Oliver Sacks | scientist | Columbia/NYU | 3 | neurologist, attended dinners |
