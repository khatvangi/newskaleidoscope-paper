# NEWSKALEIDOSCOPE
## Global Epistemic Mapping System

**Master Project Record — Version 1.0 — March 2026**

> This document is the canonical reference for the NewsKaleidoscope project. It captures all architectural decisions, empirical findings, open issues, and research directions. Update it before beginning each new Claude Code session. Never let the code outpace this document.

---

## 1. What This Is

NewsKaleidoscope takes a single geopolitical event and produces a structured map of how different regions, cultures, religions, and institutions frame that event — anchored to primary data verification where quantitative claims can be checked against authoritative sources.

This is not a bias-rating tool. It is not a news aggregator. It is an **epistemic mapping system** — a way of seeing the full landscape of how human civilization processes a single event through different modes of knowing.

> **No existing system does this.** Ground News compares US left/right framing. Nobody does civilizational + religious + data-verification + Tier 3 vernacular sources together.

### Two Arcs Running Simultaneously

| Arc 1 — The Tool | Arc 2 — The Research Program |
|---|---|
| A living, event-driven intelligence platform. Every major geopolitical event gets a page. Multi-tier ingestion. Emergent taxonomy. Mirror Gap. Absence report. Tier 3 sermons, podcasts, vernacular press. Deployed publicly via Cloudflare Pages. | A series of publishable papers generated as byproduct of the tool. The tool provides the data. The papers provide the analysis. Each strengthens the other's credibility. |

---

## 2. Hardware & Infrastructure

| Machine | GPU | VRAM | Role |
|---|---|---|---|
| nitrogen | RTX A4000 | 16 GB | Web infra, pipeline orchestration, Cloudflare deploy, git |
| boron | 2× TITAN RTX | 48 GB | llama-server inference — Qwen3:32B primary, council models |

### Stack

- Python — pipeline orchestration
- PostgreSQL — analytical database (additive-only, immutable runs)
- llama-server on boron (llama.cpp, tensor-split across 2 GPUs) — LLM inference, zero API cost
- Helsinki-NLP NLLB-200 — bulk translation (CPU, fast, purpose-built)
- faster-whisper large-v3 on boron — ASR for audio/video Tier 3
- Cloudflare Pages — public deployment from git
- GDELT API — gap-fill ingestion (free, no key)
- spaCy — syntactic analysis (passive voice, attribution, elaboration)
- Domains: thebeakes.com (current), dedicated domain TBD

---

## 3. What Is Built and Working

### Pipeline — Proven on Iran Strike Event

| Component | Status | Notes |
|---|---|---|
| GDELT ingestion | Working | 47 GDELT + 29 curated RSS = 96 attempted, 94 in final corpus |
| RSS curated ingestion | Working | 29 flagship outlets, direct feed |
| Helsinki-NLP translation | Working | NLLB-200 fallback for Persian and rare languages |
| Two-pass LLM analysis (Qwen) | Working | Pass 1: free-form framing. Pass 2: emergent clustering |
| Multi-label taxonomy | Working | position_types is array, not single value |
| Original language term preservation | Working | Extracted before translation, stored verbatim |
| Absence flags per article | Working | What each article omits, per-article |
| Uncertainty/confidence scoring | Working | Per article, with reason field |
| LLM Council (3-model) | Working | Qwen3:32b + Gemma-3-27B + Mistral-Small-3.1-24B |
| Consensus engine | Working | HIGH/MEDIUM/CONTESTED with dissent recording |
| Cluster stability testing | Working | Perturbation analysis implemented |
| Coverage gaps report | Working | Auto-generated after each run |
| Absence report | Working | Includes unspeakable positions section |
| Register analysis (Axis 2) | Working | Session 4 — 9 register types |
| Embedded assumptions probe | Working | Session 4 — who is default legitimate actor etc. |
| PostgreSQL backend | Working | Additive schema, run_id versioning |
| Immutability enforcement | Working | No overwrites, all runs preserved |
| HTML output via Cloudflare Pages | Working | Static, event-driven |

---

## 4. Empirical Findings — Iran Strike Corpus

94 articles, 42 countries, 17 languages. All findings below are from this corpus and require validation across future events.

### 4.1 The Five Emergent Clusters (session_001 — LLM Pass 2)

> These clusters emerged from Qwen reading all 94 framing descriptions and grouping by epistemic stance — NOT from sentence embeddings. They are analytically real.

| Cluster | Articles | Geography | Council H/M/C |
|---|---|---|---|
| Strategic Necessity of US-Israeli Military Action | 11 | Western-aligned, E. Europe | 0 / 5 / 6 |
| Legitimacy of US-Israeli Defensive Actions | 7 | Western-aligned | 0 / 2 / 5 |
| Critique of US Hegemony and Destabilization | 8 | China, HK, Qatar, S. Africa | 0 / 4 / 4 |
| Diplomatic and Technical Resolution Focus | 8 | Europe, India, Philippines | 0 / 2 / 6 |
| Regional and Ethical Criticisms | 20 | Iran, diaspora, Global South | 1 / 10 / 9 |
| Singletons | 4 | Various | — |
| Unassigned | 37 | US, Australia, Germany, Italy, NG, KR... | — |

### 4.2 LLM Council Results — The 2.1% Finding

| Confidence Level | Count | % of corpus |
|---|---|---|
| HIGH (all 3 models agree) | 2 | 2.1% |
| MEDIUM (2 models agree) | 37 | 39.4% |
| CONTESTED (no consensus) | 55 | 58.5% |

> **Finding:** Only 2 of 94 articles produced three-model consensus. 58.5% are genuinely contested — three models trained on different data, reading the same text, reaching different conclusions. This is not a pipeline failure. It means epistemic position in political journalism is not a stable textual property but a contested reading produced by the interaction between text and interpreter. This challenges the premise of every automated media bias tool currently in existence.

### 4.3 Model Dissent Patterns

| Model | Outlier Rate | Character |
|---|---|---|
| Qwen3:32B | 20% | Most conformist — did initial extraction, partial anchoring effect |
| Gemma-3-27B | 38% | Middle — independent but moderate |
| Mistral-Small-3.1-24B | 41% | Most independent — highest dissent rate, most likely to catch what Qwen missed |

Note: Qwen's lower outlier rate may reflect anchoring — other models respond to Qwen-shaped task framing. True independence requires prompt randomization across models in future sessions.

All three models' complete outputs are preserved in the `model_readings` JSONB column of `llm_council_verdicts` — never summarized, never discarded. This is the raw research record for future paper analysis.

### 4.4 The 37 Unassigned Articles — Geographic Signal

> **Finding:** The 5-cluster framework's blind spot is NOT the Global South. It is ambivalent center-Western journalism. All 4 US articles, both Australian, both German, both Italian, both Nigerian articles were unassigned. Meanwhile Qatar (Al Jazeera), South Africa, and Iran were well-classified. The framework captured explicit stances but failed on 'view from nowhere' journalism and non-political framings.

| Language | % Unassigned |
|---|---|
| Italian | 100% |
| Korean | 100% |
| Romanian | 100% |
| Spanish | 75% |
| German | 67% |
| English | 40% (but 21/37 unassigned are English) |

### 4.5 The Two-Axis Framework — Session 4 Discovery

> The two-axis framework is now empirically grounded. Axis 1 = Political position (5 clusters). Axis 2 = Epistemic register (9 modes). Every article has a coordinate, not just a cluster label.

| Register | Count | % of 37 unassigned |
|---|---|---|
| technical_strategic | 30 | 81% |
| political | 20 | 54% |
| ethical_moral | 13 | 35% |
| economic | 8 | 22% |
| legal | 7 | 19% |
| biographical | 6 | 16% |
| diplomatic | 4 | 11% |
| spiritual_eschatological | 3 | 8% |
| view_from_nowhere | 1 | 3% — effectively dissolved into technical_strategic |

### 4.6 The Technical-Strategic Register — Central Finding

> **MAJOR FINDING:** 'View from nowhere' does not exist as a register. It dissolved under analysis. What looked like neutrality — 81% of unassigned articles — is actually technical_strategic register: a specific epistemic mode that presents political assumptions as technical facts. Western press does not perform neutrality. It performs technocracy. The neutrality is the ideology, and it is harder to read precisely because it is more sophisticated concealment.

**ABC News embedded assumptions (article 37):**
- Default legitimate actor: US and Israel — their military actions require minimal justification
- Named casualties: Iranian protest casualties named (7,000); US/Israeli casualties "remain hypothetical"
- Implicit question: "Will the US strike Iran?" — not "What are the consequences for Iran?"

The asymmetry is not in what is said. It is in what is treated as real vs. speculative. That is not detectable by any existing bias tool.

### 4.7 Novel Frames from the 26 Unclassifiable Articles

These frames are orthogonal to the 5 clusters — not variations, but genuinely different epistemic modes:

- **Performative diplomacy** (Clarín, Argentina) — diplomacy as theater, not genuine resolution. Latin American cynicism rooted in decades of being on the receiving end of great power negotiations.
- **Presidential narrative control** (South Korea) — event filtered through domestic leadership legitimacy. Applied to non-Western leaders; never applied by Western press to Western leaders doing the same.
- **Commercial leverage as diplomatic strategy** (Iran International) — sanctions as the real weapons, military strikes as theater. How Iran reads its own situation.
- **Post-clerical legitimacy vacuum** (Al-Monitor) — who rules Iran after the clerics? The most structurally sophisticated frame in the corpus, invisible in Western coverage.
- **Proxy justification framework** (German press) — Israel striking first as legal loophole for US involvement. A specifically European legal-political reading.
- **Domestic political cohesion as prerequisite for regional diplomacy** (Dawn, Pakistan) — you cannot have external diplomacy without internal unity.

### 4.8 The 97% Internal Tensions Finding

74 of 76 articles (97%) hold contradictory positions simultaneously. This is not a pipeline artifact. It is a finding about how geopolitical events are processed by media globally. Almost no outlet has a clean, coherent position — they are all navigating competing allegiances, economic interests, historical grievances, and audience expectations simultaneously.

### 4.9 Session 5 — The Strategic Ambiguity Finding

Hypothesis tested: passive voice ratio and attribution rate predict model disagreement. Result: Both failed (r=-0.03, p=0.79; r=-0.08, p=0.43).

Confirmed finding: elaboration ratio NEGATIVELY correlates with CONTESTED confidence (r=-0.29, p=0.014). Vocabulary framing gap also negatively correlates (r=-0.31, p=0.011). Balance defeats classification. One-sided articles are easy to classify. Symmetrical articles defeat three-model consensus.

Implication: sophisticated bias has migrated entirely out of detectable structure into presuppositional framing. The balanced surface is the concealment mechanism. This inverts the premise of every existing media bias tool — asymmetry is readable, symmetry is where the sophisticated bias hides. Presupposition extraction is the critical remaining analytical layer.

Structural finding: 308 direct quotes for US/Israeli officials vs. 62 for Iranian officials (5:1 ratio) across 94 articles — structural outcome of sourcing access patterns, with editorial reinforcement. 2 civilian quotes in entire corpus. The quote ratio is access bias; the civilian absence is editorial choice about whose experience of an airstrike counts as quotable.

Vocabulary gap: Iran receives 0.19 points more condemnatory framing than US/Israel across corpus. "Strike" (62 uses near US/Israel) vs. "attack" (85 uses near Iran). "Forces" (44) vs. "regime" (45).

US articles: 38% attribution rate vs. 11% non-US (p=0.003). Heavy attribution is a stylistic convention of US journalism — not a mechanism of ambiguity, but a signature of the technical_strategic register.

---

## 5. Covert Bias Techniques — What the Pipeline Must Catch

### 5.1 Anticipatory Obfuscation

Media organizations are now aware that algorithmic bias detection exists and are adapting their language to defeat it. This is an arms race. The system must address it structurally.

> The position is no longer in the lexical content. It is in syntactic structure, elaboration asymmetry, attribution laundering, and presuppositional framing. These require different detection methods.

### 5.2 Tokenism — The False Balance Technique

One clause presenting the counter-argument while the dominant frame receives multiple paragraphs, named sources, direct quotes, and evidence.

**Dominant frame gets:**
- Named officials quoted directly
- Specific evidence cited
- Multiple paragraphs
- Active voice
- Causal explanation

**Counter-frame gets:**
- "Critics," "some observers," "opponents"
- No evidence cited
- One sentence or clause
- Passive or subordinate construction
- No elaboration or follow-through

Detection metric: `elaboration_ratio = dominant_position_score / counter_position_score`
Flag if > 4.0 (tokenism). Flag if > 8.0 (severe tokenism).

### 5.3 Syntactic Subordination

A position in a concessive clause is structurally dismissed before a single word of content is evaluated:

> *"Although some argue that the strikes violated international law, officials maintained they were necessary."* — The grammar signals how seriously to take the legal objection before any argument is made.

Detection: spaCy dependency parsing. Extract what position occupies subordinate vs. main clause. Subordinated position = structurally dismissed.

### 5.4 Asymmetric Aggression Vocabulary — The Double Standard

The same action described with different vocabulary depending on who performs it. Not detectable in a single article — requires cross-event, cross-actor analysis across the same outlet over time.

| US/Israeli action | Russian/Iranian action |
|---|---|
| strike | attack |
| operation | assault |
| targeted response | aggression |
| eliminated / neutralized | killed / massacred |
| military objective | civilian area |
| precision / surgical | indiscriminate |
| intervention | invasion |
| collateral damage | war crime |
| coalition | regime |
| self-defense | provocation |

Detection: `actor_vocabulary_matrix` in DB — outlet × event × actor × vocabulary used. Asymmetry score = `|us_framing_score - adversary_framing_score|`. Requires longitudinal corpus across multiple events.

### 5.5 Presuppositional Framing — Hardest to Catch

Claims embedded in noun phrases, treated as background fact requiring no argument:

- "Iran's nuclear weapons program" — presupposes it exists and is military. Nothing was asserted explicitly.
- "Iranian-backed Hezbollah" — presupposes Iranian control, defines Hezbollah by that relationship.
- "Defending Israel's right to exist" — presupposes the relevant frame is existence-threat, not occupation.
- "Iranian aggression" — characterization as fact, not claim.

Detection: LLM prompt specifically asking "What must be true for this sentence to make sense? What is assumed rather than argued?" Applied to US articles and technical_strategic register articles first.

---

## 6. Source Architecture

### 6.1 Four-Layer Ingestion Model

| Layer | What | Method | Status |
|---|---|---|---|
| A — Wire services | AP, Reuters, AFP — global spine, baseline | RSS direct | Planned |
| B — Regional flagships | ~800 curated outlets, flagship newspapers worldwide | RSS direct, primary | Partial (40 built) |
| C — Institutional | Think tanks, religious institutions, parliamentary records, UN statements | RSS + structured crawl | Partial (Tier 2 seeded) |
| D — Vernacular / Tier 3 | YouTube, podcasts, sermons, radio — **SIGNATURE CONTRIBUTION** | Whisper + RSS + Telethon | In progress |
| GDELT | Gap-fill only, not primary | API | Working — demoted to gap-fill |

### 6.2 Tier 3 — The Signature Contribution

> Tier 3 is what makes this project novel. No existing system does systematic vernacular/religious/broadcast ingestion with honest uncertainty quantification. The Myanmar genocide was organized in a media ecosystem nobody was monitoring. This is the cost of only tracking legible Tier 1 media.

| Tier 3 Source Type | Method | Examples | Status |
|---|---|---|---|
| YouTube broadcast archives | yt-dlp + faster-whisper | Al Jazeera Arabic, BBC Arabic, DW, France 24 | In progress |
| Religious/institutional YouTube | yt-dlp + faster-whisper | Al-Azhar, MUI Indonesia, Diyanet Turkey | In progress |
| Friday sermon archives | yt-dlp + faster-whisper, date-indexed | Post-strike Friday, major mosques | Planned |
| Vernacular political YouTube | yt-dlp + faster-whisper | Pakistani, Indian regional, Nigerian | Planned |
| Podcast RSS | Direct RSS + audio download + Whisper | Listen Notes API for discovery | Planned |
| Radio with transcripts | Crawler | BBC WS, VOA, RFI, DW — free transcripts | Planned |
| Live radio streams | ffmpeg + faster-whisper | Rural African/Asian radio | Future |
| Telegram public channels | Telethon API | Iranian opposition, Pakistani political, Arabic Islamic | Planned |

**ASR Quality Standards (non-negotiable):**
- faster-whisper large-v3 on boron GPU
- Word-level confidence scores stored per transcript
- Average confidence < 0.75 = flagged LOW CONFIDENCE, displayed with explicit warning in UI
- Back-translation verification for high-stakes Tier 3 sources
- Language-specific fine-tuned models for Arabic and Hindi/Urdu where available
- Every Tier 3 source tagged: source_type, asr_confidence, platform, institutional_affiliation

### 6.3 Beyond GDELT — Additional Ingestion Sources

| Source | What it adds | Priority |
|---|---|---|
| UN Security Council transcripts | Every nation's official position on record, same day as event. Free, structured XML. | HIGH — do next |
| Parliamentary records | Hansard (UK), Bundestag, Indian Parliament, South African NA — verbatim official debate | MEDIUM |
| Non-Western think tanks | ORF India, ECFR Europe, Al-Ahram Centre Egypt, SAIIA S. Africa, Lowy Australia | HIGH |
| Reddit | r/worldnews, r/geopolitics + non-English subreddits. Label explicitly as 'Anglophone online discourse', not public opinion | MEDIUM |
| Long-form journals | Foreign Affairs, Foreign Policy, Le Monde Diplomatique — where establishment frame is articulated first | MEDIUM |
| Diaspora press | Iranian-American, Arab-American, Indian-American press — third frame between state media and US mainstream | HIGH |

---

## 7. Analytical Modules — Built and Planned

### 7.1 Built

- LLM Council — 3-model consensus engine with dissent recording
- Two-pass clustering — Pass 1 free-form framing, Pass 2 emergent grouping
- Register analysis — 9 epistemic register types (Axis 2)
- Embedded assumptions probe — who is default legitimate actor, whose casualties are named
- Absence detection — what each article omits, what the full corpus refuses to say
- Cluster stability testing — perturbation analysis
- Coverage gaps report — which regions/languages are absent

### 7.2 Planned — Next Sessions

- **Syntactic analyzer (spaCy):** passive_voice_ratio, attribution_rate, direct_quote_balance by actor, opening_subject, precision_asymmetry, casualty_specificity
- **Elaboration scorer:** elaboration_ratio per article, tokenism flagging at > 4.0 and > 8.0 thresholds
- **Concessive clause detector:** what position is grammatically subordinated in each article
- **Vocabulary asymmetry matrix:** actor × outlet × event × sanitizing/condemnatory vocabulary. Longitudinal from day one.
- **Presupposition extractor:** LLM prompt asking what must be true for each sentence to make sense
- **US Mirror Gap module:** domestic_ratio scoring, absent_subjects, mirror_gap_report for side-by-side display
- **Event typing system:** military/election/economic/disaster — different frameworks, different source activation

### 7.3 The US Frame — Separate Module

> US media is not just politically biased — it has civilizational narcissism. It cannot perceive itself as an external actor. Every other country's media covers the US as a foreign power with interests and impacts. US media covers the US as the default subject of history. This is not left/right. NYT and Fox do it equally.

The Mirror Gap feature: US self-perception vs. world perception, side by side, no commentary. The gap speaks for itself. This is the most politically powerful output of the system and requires no editorial voice.

---

## 8. Database Rules — Immutability Protocol

> **CRITICAL:** The DB is a research record, not a state store. Every run is preserved. Nothing is ever overwritten. Comparison between runs is a feature, not a problem. Claude Code must never UPDATE or DELETE analytical rows.

### 8.1 Immutability Rules

- Every analytical run gets a run_id (timestamp-based)
- All DB inserts include run_id
- No UPDATE or DELETE on: articles, analyses, council_votes, clusters tables
- New runs produce NEW rows alongside old ones
- Invalid runs (e.g. sentence_embedding attempt) are marked valid=false — NOT deleted
- Before touching any file or table: report what exists, state what will be added vs. preserved, wait for confirmation if destructive

### 8.2 Core Schema Tables

| Table | Key Fields | Notes |
|---|---|---|
| events | id, name, date, type (military/election/economic/disaster), description | Event typing required |
| sources | id, name, domain, country, region, tier (1/2/3), language, platform, bias_notes, funding_source | |
| articles | id, event_id, source_id, url, raw_text, original_language, fetch_method, asr_confidence | asr_confidence for audio |
| analyses | id, article_id, model_used, position_types[], register[], tension_detected, absence_flags[], embedded_assumptions{}, confidence, run_id | run_id mandatory |
| council_votes | id, article_id, model, position_types[], confidence, dissent_from_consensus, run_id | Per-model record |
| clusters | id, event_id, run_id, method, label, article_ids[], stability_score, valid | valid=false for failed attempts |
| absence_report | id, event_id, run_id, unrepresented_regions[], unspeakable_positions[], voiceless_populations[] | |
| mirror_gap | id, event_id, run_id, us_frame_summary, world_frame_summary, domestic_ratio_avg, absent_subjects[] | |
| actor_framing | id, outlet, event_id, actor, sanitizing_terms[], condemnatory_terms[], framing_score | Longitudinal — built across events |

---

## 9. Open Issues — Must Address Before Scaling

| Issue | Severity | Proposed Fix | Status |
|---|---|---|---|
| Qwen anchoring effect in council | HIGH | Randomize prompt order across models, prevent Qwen from always going first | Unstarted |
| Cluster stability not fully validated | HIGH | Run same corpus twice, measure cluster overlap score | Partial |
| Event typing not implemented | HIGH | Add event_type field, build domain-specific frameworks for each type | Unstarted |
| Syntactic analysis layer missing | HIGH | Build syntax_analyzer.py with spaCy — passive voice, attribution, elaboration | Unstarted |
| Vocabulary asymmetry matrix | HIGH | Build actor_framing table, seed sanitizing/condemnatory lexicon | Unstarted |
| 37 unassigned articles — register analysis done, frame clustering incomplete | MEDIUM | Session 5: cluster on register + embedded assumptions vectors | Partial |
| Speed: 89 min for 94 articles through council | MEDIUM | Helsinki-NLP for all translation, Qwen only for analysis — saves 40-50% | Partial fix done |
| Presupposition extraction not implemented | MEDIUM | Add to Pass 2 prompt for technical_strategic register articles | Unstarted |
| Paywalled sources — 20 articles skipped | MEDIUM | Accept limitation, document which outlets are inaccessible, note in UI | Accepted |
| Iranian domestic press absent from corpus | MEDIUM | Add Iran International, Press TV, Kayhan, Shargh, ISNA to outlets.json | Unstarted |
| UN Security Council transcripts not ingested | MEDIUM | Free, structured XML — build parser, high analytical value | Unstarted |
| Tier 3 pipeline: YouTube/podcast/Whisper | MEDIUM | In progress — complete and validate before scaling | In progress |
| Output design undecided | HIGH | Separate design discussion required — see Section 11 | Pending |

---

## 10. Research Arc — Papers

### Paper 1 — Methodology
Two-axis epistemic mapping framework. The pipeline itself as contribution to computational journalism / media studies.

> Central argument: Current media bias analysis operates on a single axis — political position. This is insufficient because (1) it cannot detect position encoded in register rather than content, and (2) it cannot capture epistemic diversity of global media operating in modes — legal, spiritual, economic, strategic — that don't map onto Western political categories.

### Paper 2 — The Mirror Gap
Systematic measurement of US self-perception vs. world perception across multiple events. Longitudinal if pipeline runs long enough. Finding: the gap between how America narrates itself and how the world narrates America is one of the most consequential epistemic facts in contemporary geopolitics and is currently invisible to the people inside it.

### Paper 3 — The Sermon Corpus
First systematic analysis of Islamic institutional response to geopolitical events. Al-Azhar vs. Diyanet (Turkey) vs. MUI (Indonesia) vs. ISNA (North America) — same event, different registers. The Friday after the Iran strike, indexed by date, across denominations and geographies.

### Paper 4 — Absence as Data
Unspeakable positions as structural phenomenon in global media. What the corpus collectively refuses to articulate — Iranian nuclear program as self-defense, US presence as colonial — are not fringe positions. They are held by significant portions of the world population and structurally excluded from legible media.

### Paper 5 — Internal Tensions
97% internal contradiction rate across 87 articles. What does it mean that almost no outlet holds a coherent position on a major military event? What are the most common tension types? Hypothesis: outlets simultaneously invoking international law and accepting US exceptionalism to it.

### Paper 6 — Algorithmic Anticipation
How sophisticated media organizations adapt framing to defeat automated bias detection. Technical-strategic register as the dominant Western epistemic mode — performs objectivity by presenting political assumptions as technical facts. Vocabulary asymmetry documented across multiple events.

---

## 11. Output Design — The Make-or-Break Decision

> This section is the most important undecided question in the project. The analytical output is sophisticated. How it is presented determines public impact. This requires a dedicated design discussion before any frontend code is written.

### 11.1 Format Decision

The output is a written analytical report with embedded data visualizations — not a dashboard, not a pure article. The writing is load-bearing. Visualizations support the argument, they do not replace it.

Weekly cadence: one event per week, thoroughly covered. The constraint forces editorial discipline — you cannot cover everything, so you cover one thing completely.

### 11.2 Reference Models

| Reference | What to take from it |
|---|---|
| The Economist | One strong thesis per piece. Editorial confidence. Not 'here are perspectives' but 'here is what the data shows.' |
| Our World in Data | Progressive disclosure. Simple chart first. Drill into methodology if you want. Complexity is there but not mandatory. |
| Rest of World | Closest editorial analog. Deep reported pieces, non-Western perspectives, small team high impact, weekly cadence. |
| Flourish | Free visualization layer. Embeddable charts, maps, timelines. Does not require JavaScript framework. |
| NYT data journalism | Data as emotional hook, not information delivery. One number that stops you cold, then earns complexity underneath. |

### 11.3 The Emotional Hook — Mirror Gap

The Mirror Gap is the feature that needs to open every event page. Two columns. US frame vs. world frame. Eight words each. No explanation needed. The gap is visceral. Then you go deeper.

> **US FRAME:** "Decisive action to prevent nuclear threat, defend democratic ally."
> **WORLD FRAME:** "Unilateral strike bypassing UN Security Council — fourth US military intervention in region since 2001."
>
> No commentary. The reader sees it. The gap speaks for itself.

### 11.4 Page Structure (Draft)

1. Mirror Gap — US frame vs. world frame, side by side, visceral
2. Factual core — primary data verification, what happened, what claims check out
3. The epistemic map — 2D visualization of clusters by position × register
4. Cluster narratives — what each cluster believes and why, with representative sources
5. Novel frames — the 26 frames that resist standard categories
6. Tier 2 — religious/institutional response
7. Tier 3 — vernacular/sermon/podcast layer with confidence caveats
8. What nobody said — absence report, unspeakable positions
9. Confidence map — what is reliable, what is uncertain, what is missing
10. Methodology note — brief, honest, links to full methods

---

## 12. Build Sequence — Next Sessions

| Session | Goal | Key Deliverables |
|---|---|---|
| Session 5 | Syntactic analysis layer | syntax_analyzer.py with spaCy — passive voice, attribution, elaboration ratio, concessive detection |
| Session 6 | Vocabulary asymmetry + presupposition | actor_framing table, lexicon seeded, presupposition extraction prompt, run on 94 articles |
| Session 7 | UN + parliamentary ingestion | UN Security Council transcript parser, 2-3 parliamentary sources |
| Session 8 | Tier 3 completion | Whisper pipeline stable, sermon harvester working, podcast RSS ingestion, all feeding DB |
| Session 9 | US Mirror Gap module | domestic_ratio scoring, absent_subjects, mirror_gap_report generation |
| Session 10 | Output design implementation | After design discussion — report generator, visualization layer, Cloudflare deployment |
| Ongoing | New events | One event per week, full pipeline, comparative analysis building over time |

---

*NewsKaleidoscope — If you want to understand what the world actually thinks, you have to go where the world actually gets its information.*

**Update this document before each Claude Code session. The code must never outpace the record.**
