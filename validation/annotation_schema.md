# annotation schema — NewsKaleidoscope human validation

version: 1.0 (pre-pilot)
last revised: 2026-03-07

---

## overview

this schema operationalizes four annotation dimensions for human validation
of LLM-extracted epistemic framing. each dimension has a formal definition,
a decision procedure, positive and negative examples, and a conflict
resolution rule.

annotators should read this document in full before beginning the pilot.
the schema will be revised after the 5-article pilot based on annotator
feedback and disagreement analysis. the post-pilot version is locked for
the main annotation round.

---

## dimension 1: framing_description

### definition

a 1–3 sentence description of the article's epistemic position on the event.
the description must capture (a) who the article treats as the legitimate
actor, (b) what response the article implicitly or explicitly endorses, and
(c) what the article assumes the reader already accepts. the description
should use the article's own vocabulary and conceptual categories, not
external political science labels.

### decision procedure

1. read the article in full.
2. ask: "if i had to explain to a colleague what this article *wants me to
   believe* about this event, what would i say?"
3. write that explanation in 1–3 sentences.
4. check: does my description distinguish this article from other articles on
   the same event? if not, make it more specific.
5. check: does my description use the article's own words/concepts, or have i
   imposed my own framework? revise if the latter.

### positive examples

**example 1** (article from al jazeera on US-Iran strikes):
> "The article frames the strikes as an escalation of US aggression in the
> region, treating Iranian sovereignty as the violated norm and US military
> presence as the destabilizing factor. It assumes readers accept that the
> Middle East has been subject to decades of Western military intervention."

*why this qualifies:* identifies the legitimate actor (Iran, via sovereignty),
the endorsed response (de-escalation of US presence), and the assumed context
(history of Western intervention). uses the article's framing vocabulary
("escalation," "sovereignty").

**example 2** (article from WSJ on US-Iran strikes):
> "The article presents the strikes as a calculated response to Iran's nuclear
> program, treating US intelligence assessments as authoritative and framing
> military action as the last credible deterrent after diplomatic failure."

*why this qualifies:* identifies authority structure (US intelligence as
credible), endorsed response (military deterrence), assumed context (diplomacy
has failed).

**example 3** (article from xinhua on US-Iran strikes):
> "The article positions China as a stabilizing force advocating dialogue,
> frames the US action as unilateral and destabilizing to regional trade
> routes, and assumes readers care primarily about economic consequences
> rather than security dynamics."

*why this qualifies:* captures the distinctive Chinese framing (economic
lens, China as stabilizer) rather than defaulting to a generic "opposes US"
description.

### negative examples

**negative 1** — too generic:
> "The article is critical of the US strikes."

*why this fails:* does not distinguish this article from hundreds of others.
no information about authority structure, endorsed response, or assumptions.

**negative 2** — imposes external framework:
> "This is a realist perspective emphasizing balance of power dynamics."

*why this fails:* uses political science taxonomy ("realist," "balance of
power") instead of the article's own vocabulary. the annotation should
describe what the article says, not classify it.

**negative 3** — summarizes content, not framing:
> "The article reports that the US struck three sites in Iran and Iran
> retaliated with missile launches."

*why this fails:* describes factual content, not epistemic framing. the
question is not "what happened" but "how does this article want me to
understand what happened."

### conflict resolution

if the annotator cannot determine the framing after two readings, mark the
article as "ambiguous" and describe the ambiguity: "article oscillates
between X framing and Y framing without committing to either." this is
valid data — ambiguity is a finding, not a failure.

---

## dimension 2: position_types

### definition

a set of 1–4 labels describing the epistemic positions the article occupies.
these are multi-label (an article can hold multiple positions simultaneously)
and drawn from the article's content, not a predefined taxonomy. each label
is a short phrase (3–8 words) that names a stance.

### decision procedure

1. after writing the framing_description, extract the distinct claims or
   stances the article takes.
2. for each, write a short phrase that names the position.
3. check: are any of these positions in tension with each other? if so,
   include both — internal tension is data.
4. check: would removing any label lose information about this article's
   epistemic position? if not, remove it.

### positive examples

**example 1:** `["US military authority as legitimate deterrent", "diplomacy as exhausted"]`

*why:* two distinct positions — one about authority, one about alternatives.
both are necessary to capture the article's full stance.

**example 2:** `["Iranian sovereignty as inviolable", "US as colonial aggressor", "regional solidarity against intervention"]`

*why:* three linked but distinct positions. the third (regional solidarity)
adds information beyond the first two.

**example 3:** `["economic stability as primary concern", "both sides reckless"]`

*why:* captures a distinctive framing that prioritizes economics over
security and refuses to take sides — common in financial press and some
Asian outlets.

### negative examples

**negative 1:** `["pro-US"]`

*why:* too coarse. does not distinguish between endorsing strikes, endorsing
diplomacy, endorsing sanctions, or endorsing any of dozens of US positions.

**negative 2:** `["realist", "hawkish", "neoconservative"]`

*why:* political science jargon, not positions derived from the article.

**negative 3:** `["supports peace", "wants stability", "hopes for diplomacy", "against war"]`

*why:* four labels that all say the same thing. redundant labels waste
annotator effort and inflate false specificity.

### conflict resolution

if two annotators produce different position labels that are semantically
equivalent (e.g., "US as aggressor" vs "US military action as aggression"),
these count as agreement. semantic equivalence is determined by BERTScore
≥ 0.85 between label texts. if below that threshold, treat as disagreement
and discuss during reconciliation.

---

## dimension 3: register

### definition

the communicative register of the article: the mode of discourse it employs.
single-label, selected from a closed set of 7 options.

### options

| register | definition | signal words/patterns |
|----------|------------|----------------------|
| `neutral_analytical` | presents facts and analysis without emotional coloring or advocacy. attributes claims to sources. | "according to," "analysts say," conditional tense |
| `alarmed` | presents the situation as urgent, dangerous, or threatening. may or may not advocate a specific response. | "crisis," "threat," "unprecedented," urgency markers |
| `triumphant` | frames the event as a victory or vindication for one side. celebratory tone. | "decisive," "showed strength," "finally" |
| `mournful` | centers human suffering, loss, or tragedy. empathetic register. | casualty details, named victims, "devastation" |
| `ironic` | uses rhetorical distance, sarcasm, or subversion. questions official narratives through juxtaposition. | scare quotes, juxtaposition of claims with contradicting evidence |
| `propagandistic` | presents a single narrative without acknowledging alternatives. heavy use of loaded language. | no attribution, absolute claims, dehumanizing language |
| `diplomatic` | formal, hedged language typical of official communications or institutional press. | "expressed concern," "called upon," "reaffirmed commitment" |

### decision procedure

1. read the article and identify the dominant tone — not occasional phrases,
   but the overall communicative mode.
2. if the article shifts register (e.g., analytical in opening, alarmed in
   closing), choose the register that dominates by word count.
3. if genuinely split, mark the dominant one and note the secondary in
   `annotator_notes`.

### positive examples

**neutral_analytical:** reuters report attributing all claims, conditional
language, no advocacy. *why:* wire service standard — presents, doesn't
advocate.

**propagandistic:** state media article with no source attribution, refers to
enemy as "terrorists" throughout, presents single narrative as fact. *why:*
closed epistemic frame, no alternatives acknowledged.

**ironic:** editorial that quotes official justifications at length then
immediately presents contradicting evidence without explicit commentary.
*why:* the juxtaposition does the argumentative work, not direct claims.

### negative examples

**not alarmed — actually analytical:** article uses the word "crisis" in the
headline but the body is measured analysis of strategic options. *why:*
headline register ≠ article register. annotate the body.

**not propagandistic — actually triumphant:** government-aligned outlet
celebrating a military success. *why:* propagandistic requires epistemic
closure (no alternatives acknowledged). triumphant can acknowledge the
opposing side's existence while celebrating a win.

### conflict resolution

if uncertain between two registers, choose the one that would be more
informative if correct. e.g., if torn between "neutral_analytical" and
"diplomatic," choose "diplomatic" — the distinction carries more analytical
value than defaulting to neutral.

---

## dimension 4: embedded_assumptions

### definition

a list of 1–4 claims that the article treats as given — premises that are
not argued for but relied upon. these are the things a reader from a
completely different political tradition would notice as "wait, why does the
article assume that?"

### decision procedure

1. for each major claim the article makes, ask: "what does this claim
   presuppose?"
2. for each presupposition, ask: "is this presupposition explicitly argued
   for in the article, or just assumed?"
3. if assumed, ask: "would a reader from [Iran / China / Nigeria / Brazil]
   accept this assumption without argument?"
4. if the answer is no, include it.

### positive examples

**example 1:** `["nuclear weapons are inherently destabilizing", "the US has the right to act preemptively against nuclear proliferation"]`

*why:* both are substantive assumptions that many articles take as given
but that are genuinely contested — e.g., some strategic theorists argue
nuclear weapons stabilize through deterrence, and preemptive action is
contested under international law.

**example 2:** `["the reader knows the history of the JCPOA", "Iran's government is a unitary rational actor"]`

*why:* the first is an assumed knowledge context; the second is a
theoretical assumption (unitary actor model) that many Iranian commentators
would dispute.

**example 3:** `["free trade is net positive for all parties", "tariffs are inherently protectionist and harmful"]`

*why:* (CS2 tariffs) economic assumptions that the article treats as
axiomatic but that are contested by heterodox economists and development
theorists.

### negative examples

**negative 1:** `["the article assumes the reader speaks English"]`

*why:* trivially true for translated articles and uninformative.

**negative 2:** `["the article is biased toward the US"]`

*why:* this is an evaluative judgment, not an identified assumption. name
the specific assumption.

**negative 3:** `["the author assumes their argument is correct"]`

*why:* vacuously true of all argumentation. not an operationalizable
annotation.

### conflict resolution

if two annotators identify different assumptions, both may be valid — this
dimension is multi-label and articles typically embed more assumptions than
any single reader notices. disagreement is resolved by asking: "is this
genuinely assumed (not argued for) in the text?" if yes, include it
regardless of whether the other annotator noticed it.

---

## general instructions

### annotation order

for each article:
1. read the article at the URL (or from cache/ directory).
2. write `framing_description` FIRST, before looking at any LLM output.
3. write `position_types` and `embedded_assumptions`.
4. select `register`.
5. THEN look at the LLM's framing output and fill in:
   - `human_agrees_with_llm`: agree / partial / disagree / unclear
   - `annotator_notes`: what the LLM got right, wrong, or missed.

this order is mandatory. looking at LLM output before writing your own
assessment biases the annotation.

### non-english articles

- if you speak the language: annotate from the original.
- if you do not: annotate from the translated text in the DB, and note
  "annotated from translation" in `annotator_notes`.
- if no translation is available and you cannot read the original: mark
  "cannot assess — language barrier" and skip.

### time budget

expect 8–12 minutes per article for the first 10, dropping to 5–8 minutes
once familiar with the schema. total for 60 articles: ~6–8 hours per
annotator.
