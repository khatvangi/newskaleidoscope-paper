# NewsKaleidoscope Manuscript Preparation Package

## Directory Structure

```
manuscript/
├── MANUSCRIPT_GUIDE.md          ← this file
├── tables/                      ← publication-ready tables (markdown + CSV)
├── figures/                     ← SVG/HTML figures for the paper
├── methodology/                 ← draft methodology sections (markdown)
├── supplementary/               ← supplementary materials
├── prompts/                     ← exact LLM prompts used
└── stats/                       ← raw statistics (CSV + text)
```

## Suggested Manuscript Structure

### Title Options
- "How the World Frames War: Emergent Epistemic Patterns in Global News Coverage of Military Conflicts"
- "Monopolar vs Multipolar: Computational Mapping of Framing Consensus Across Two Military Conflicts"
- "The Epistemic Kaleidoscope: LLM-Extracted Framing Patterns in 3,363 Articles Across 41 Languages"

### Abstract (~250 words)
- Problem: media framing analysis traditionally uses predefined categories
- Method: LLM-based open-ended extraction + emergent clustering across two conflicts
- Key finding: Ukraine 4x more unified framing than Iran (14% vs 57.7% contested)
- Implication: epistemic fragmentation tracks moral complexity of the target, not just attacker identity

### 1. Introduction
- The problem of predefined categories in media framing analysis
- Why computational methods enable emergent discovery
- Two case studies: US-Israeli strike on Iran (2026), Russian invasion of Ukraine (2022)
- Research questions

### 2. Related Work
- Framing theory (Entman, Gamson & Modigliani)
- Computational framing analysis (Card et al., Kwak et al.)
- Media coverage of military conflicts
- LLMs for content analysis (Gilardi et al., Ziems et al.)

### 3. Methodology
- 3.1 Data collection → methodology/01_data_collection.md
- 3.2 Text extraction and translation → methodology/02_text_extraction_translation.md
- 3.3 Open-ended framing extraction → methodology/03_framing_extraction.md
- 3.4 Multi-model council validation → methodology/04_council_validation.md
- 3.5 Emergent clustering → methodology/05_clustering.md
- 3.6 Infrastructure → methodology/06_infrastructure.md

### 4. Results
- 4.1 Corpus characteristics (Table 1, Figure 1)
- 4.2 Emergent framing clusters — Iran (Table 2, Figure 2)
- 4.3 Emergent framing clusters — Ukraine (Table 3, Figure 3)
- 4.4 Cross-case comparison (Table 4, Figure 4)
- 4.5 Model agreement analysis (Table 5, Figure 5)
- 4.6 Language geography of framing (Figure 6)
- 4.7 Structural absences (Table 6)

### 5. Discussion
- 5.1 Why framing consensus tracks moral clarity
- 5.2 The hegemon accountability effect
- 5.3 Distributed vs concentrated dissent
- 5.4 What structural absences reveal
- 5.5 Methodological implications: emergence vs imposition

### 6. Limitations
- LLM extraction biases (Western training data)
- GDELT source selection bias
- Historical vs real-time corpus differences
- Single-week time window
- Translation quality for low-resource languages

### 7. Conclusion

### Supplementary Materials
- S1: Full cluster inventories (119 + 93 clusters)
- S2: Per-language council agreement scores
- S3: Singleton article analysis
- S4: Country context injection texts
- S5: Exact LLM prompts
- S6: Reproducibility details (seeds, versions, times)

## Key Numbers for Quick Reference

| Metric | Iran (CS1) | Ukraine (CS1-RU) |
|--------|-----------|-----------------|
| Total articles | 1,267 | 2,096 |
| With extractable text | 1,267 | 1,863 |
| Unique sources | 330 | 717 |
| Languages | 24 | 41 |
| Pass 1 analyzed | 1,267 | 1,863 |
| Council | Full (3 models) | Sample (2 models, N=307) |
| HIGH agreement | 4.7% | 13.4% |
| MEDIUM agreement | 37.6% | 72.6% |
| CONTESTED | 57.7% | 14.0% |
| Emergent clusters | 119 | 93 |
| Singletons | 76 | 68 |
| Largest cluster | 18.5% (267) | 49.8% (927) |

## Target Venues (suggestions)

**Tier 1 (high impact)**
- Political Communication — framing analysis is their bread and butter
- New Media & Society — computational methods + global media
- Digital Journalism — methodology innovation

**Tier 2 (methods-focused)**
- Computational Communication Research — perfect fit for methods paper
- Journal of Communication — broad reach

**Tier 3 (interdisciplinary)**
- PNAS — if framed as "emergent consensus in global information systems"
- EPJ Data Science — computational social science
