# human validation instructions

## event: US-Israeli Military Strikes on Iran

## overview

you have been given 60 articles sampled from a corpus of 175 articles about US-Israel military action against Iran. the articles were analyzed by an LLM council (3 models: Qwen-32B, Gemma-27B, Mistral-24B) for their epistemic framing.

your task: independently assess each article's framing and compare to the LLM's assessment.

## what to annotate

for each article in the CSV:

1. **read the article** at the provided URL (or use cached text in cache/ directory, keyed by MD5 of URL)
2. **human_primary_frame**: in 1-2 sentences, describe how this article frames the event. use the article's own vocabulary, not political science labels.
3. **human_agrees_with_llm**: one of:
   - `agree` — the LLM framing captures the article's essential position
   - `partial` — the LLM framing is directionally correct but misses important nuance
   - `disagree` — the LLM framing mischaracterizes this article
   - `unclear` — the article is too ambiguous to assess
4. **human_cluster_label**: which cluster (from the cluster_label column) does this article best fit? or write `new: [description]` if none fit.
5. **human_notes**: any observations — e.g., "LLM missed the ironic tone", "article is actually about X not Y", etc.

## stratification notes

this sample is NOT random. it oversamples:
- **contested** articles (where the 3 models disagreed most) — these are the hardest cases
- **non-english** articles — to check whether translation artifacts affect framing
- articles from underrepresented clusters

## important

- do NOT look at the LLM framing before forming your own assessment. read the article first, write human_primary_frame, THEN compare.
- if the article URL is dead, note "URL dead" in human_notes and skip.
- for non-English articles you don't speak, note "cannot assess — language barrier" in human_notes.

## cluster definitions (for reference)

- **Regional and Ethical Criticisms**: Articles frame U.S.-Israel actions as ethically or legally flawed, emphasizing civilian harm, regional instability, or violations of international law. Often highlights Iran's 'right to self-defense.'
- **Critique of US Hegemony and Destabilization**: Articles position U.S. military actions as destabilizing, hegemonic, or economically exploitative. Contrasts U.S. 'aggression' with Iran's 'rational' or 'peace-seeking' behavior.
- **Diplomatic and Technical Resolution Focus**: Articles prioritize multilateral diplomacy, IAEA verification, or economic negotiations as the primary path to conflict resolution. Downplays military action as a last resort.
- **Strategic Necessity of US-Israeli Military Action**: Articles frame U.S.-Israel military planning as a calculated, time-sensitive strategy to address existential threats, legitimize political agendas, or preempt Iranian retaliation. Emphasizes military escalation as a 'necessary risk' or 'strategic imperative.'
- **Legitimacy of US-Israeli Defensive Actions**: Articles justify U.S.-Israel military readiness as a moral or legal right to counter Iranian aggression, framing it as a 'justified response' to nuclear threats or regional destabilization. Often cites sovereignty or self-defense.
- **Iranian Resistance as Justified Self-Defense**: Articles portray Iran's military and diplomatic responses as legitimate self-defense against U.S.-Israeli aggression, emphasizing historical grievances, nuclear rights, and regional solidarity.
- **Sovereignty and International Law as Central to Conflict Legitimacy**: Articles frame the conflict through legal and ethical lenses, emphasizing state sovereignty, international law, and the illegitimacy of preemptive strikes. Often critiques U.S.-Israel actions as violations of norms.
- **China's Strategic Gains and Regional Stability Concerns**: Articles position U.S.-Israel military actions as destabilizing and beneficial to China's regional influence, emphasizing economic diplomacy, infrastructure disruption, and long-term strategic recalibration.
- **Diplomatic Efforts as the Primary Path to Conflict Avoidance**: Articles prioritize diplomacy as the central mechanism to avert war, framing military posturing as a secondary or risky strategy. Highlights fragile negotiations, U.S. unilateralism, and the need for reciprocal concessions.
- **Justified Preemptive Military Action Against Existential Threats**: Articles frame U.S.-Israel military action as a necessary, calculated response to Iran's nuclear ambitions or regional destabilization, often citing historical precedents or existential threats. Emphasizes strategic timing, public opinion management, and operational risk mitigation.
- **Cluster 5 (4 articles)**: agglomerative clustering on all-MiniLM-L6-v2 sentence embeddings. collapsed into 84/94 mega-cluster because embeddings capture topic similarity not frame divergence.
- **Cluster 4 (1 articles)**: agglomerative clustering on all-MiniLM-L6-v2 sentence embeddings. collapsed into 84/94 mega-cluster because embeddings capture topic similarity not frame divergence.
- **Cluster 3 (2 articles)**: agglomerative clustering on all-MiniLM-L6-v2 sentence embeddings. collapsed into 84/94 mega-cluster because embeddings capture topic similarity not frame divergence.
- **Cluster 2 (84 articles)**: agglomerative clustering on all-MiniLM-L6-v2 sentence embeddings. collapsed into 84/94 mega-cluster because embeddings capture topic similarity not frame divergence.
- **Cluster 1 (3 articles)**: agglomerative clustering on all-MiniLM-L6-v2 sentence embeddings. collapsed into 84/94 mega-cluster because embeddings capture topic similarity not frame divergence.
