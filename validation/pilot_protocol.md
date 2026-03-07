# pilot annotation protocol

version: 1.0
last revised: 2026-03-07

---

## purpose

validate the annotation schema before the main annotation round. identify
ambiguities in definitions, calibrate annotator understanding, and revise
the schema based on actual disagreements. the pilot is complete when two
annotators achieve acceptable preliminary agreement on the revised schema.

---

## participants

minimum 2 annotators. at least one must be bilingual (English + one of:
Arabic, French, Spanish, Chinese, Persian). both must read
`annotation_schema.md` in full before beginning.

---

## materials

5 articles selected from the 60-article stratified sample. selection
criteria: 2 English, 1 French or Spanish, 1 Arabic or Persian or Chinese,
1 article previously flagged as "contested" by the LLM council. the pilot
articles should span at least 3 different clusters.

pilot article IDs will be recorded in `validation/pilot_articles.csv`.

---

## procedure

### phase 1: independent annotation (day 1)

1. each annotator independently annotates all 5 articles following the
   schema's annotation order (framing_description first, then position_types,
   register, embedded_assumptions, then LLM comparison).
2. annotators do not communicate during this phase.
3. each annotator records time spent per article.

### phase 2: disagreement review (day 2)

1. compare annotations side by side.
2. for each article, record:
   - which dimensions had agreement
   - which had disagreement
   - whether the disagreement was:
     - **schema ambiguity**: the schema doesn't clearly distinguish the two
       interpretations (→ revise schema)
     - **reading difference**: annotators read the article differently
       (→ discuss, no schema change needed)
     - **genuine disagreement**: both interpretations are defensible
       (→ document as legitimate variation, no schema change)
3. for each schema ambiguity, draft a revision.

### phase 3: schema revision (day 2–3)

1. implement all agreed revisions to `annotation_schema.md`.
2. increment the version number.
3. document every revision in `validation/schema_revisions.md`:
   - what was ambiguous
   - what the disagreement was
   - what was changed
   - why the new wording resolves the ambiguity
4. both annotators sign off on the revised schema.

### phase 4: re-annotation check (optional, day 3)

if >2 of the 5 articles had schema-ambiguity disagreements, re-annotate
those articles under the revised schema. verify that the revision resolved
the ambiguity. if it didn't, revise again.

---

## pilot exit criteria

the pilot is complete and the main annotation may begin when:

1. the schema has been revised based on actual disagreements (even if
   zero revisions were needed — document that explicitly).
2. both annotators agree the schema is unambiguous for the types of
   articles in the corpus.
3. preliminary agreement on register (categorical) ≥ 70% exact match.
4. preliminary BERTScore on framing_description ≥ 0.80 mean.

if criteria 3 or 4 are not met after one revision cycle, this indicates
the task may be fundamentally difficult for human annotators — document
this and proceed with the main annotation anyway, but add a caveat to
the paper's IAA reporting.

---

## documentation

all pilot materials are stored in `validation/`:

```
validation/
  annotation_schema.md          # current schema (post-pilot version)
  pilot_protocol.md             # this document
  schema_revisions.md           # log of all changes during pilot
  pilot_articles.csv            # the 5 pilot articles
  pilot_annotations_A.csv       # annotator A's pilot output
  pilot_annotations_B.csv       # annotator B's pilot output
  pilot_disagreement_log.md     # article-by-article disagreement analysis
```

---

## timeline

| phase | duration | dependencies |
|-------|----------|-------------|
| independent annotation | 1 day | annotators have read schema |
| disagreement review | 0.5 day | phase 1 complete |
| schema revision | 0.5 day | phase 2 complete |
| re-annotation check | 0.5 day (optional) | phase 3 complete |
| **total** | **2–3 days** | |

the main annotation (60 articles × 2+ annotators) begins immediately
after pilot exit criteria are met.
