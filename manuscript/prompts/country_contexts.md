# Country Context Injection

Source: `country_contexts.json` (58 entries)

Injected into Pass 1 prompts via the `{country_context}` template variable to compensate for LLM Western training bias. Each entry provides 2-3 sentences covering: relationship to US military action, regional position, and domestic media framing factors.

## Structure

Each country entry contains:
- `context` — narrative text injected directly into the prompt
- `region` — geographic classification
- `relationship_to_us_military` — one of: allied, adversarial, complicated, neutral, self
- `key_framing_factors` — list of factors that shape media coverage

## Sample Entries (10 of 58)

| Country | Relationship | Context (injected into prompt) |
|---------|-------------|-------------------------------|
| Iran | adversarial | Direct target of US military threats and covert operations since the 1953 CIA-backed coup and 1979 hostage crisis. State-controlled media frames all US military action as imperialist aggression, with nuclear program presented as sovereign right. Revolutionary Guard ideology treats resistance to US hegemony as foundational national identity. |
| Israel | allied | Closest US military ally in the Middle East, receiving $3.8B annually in security assistance and sharing intelligence on Iran. Israeli media broadly supports containment of Iranian nuclear capability, framing it as existential threat. Domestic debate centers on tactical approach rather than whether Iran should be confronted. |
| China | adversarial | Strategic competitor to US with major Iranian oil imports and Belt and Road investments across the Middle East, viewing US military action as destabilizing to Chinese economic interests. Chinese state media frames US military action as hegemonic overreach and evidence of Western decline, contrasting it with China's economic development model. Coverage serves dual purpose of discrediting US-led order while signaling to domestic audience that CCP governance is superior. |
| India | complicated | Non-aligned tradition creates instinct to avoid taking sides in US-Iran tensions, while growing US defense partnership (QUAD, defense deals) pulls toward Washington alignment. Indian media is massive and diverse, but Hindu nationalist outlets under BJP increasingly frame Muslims as security threats, complicating coverage of US action against Muslim-majority Iran. India's large Shia minority and historical Iran ties prevent full alignment with anti-Iran framing. |
| South Africa | adversarial | ANC government maintains strong anti-imperialist foreign policy rooted in liberation struggle, with institutional solidarity with Palestinian cause and skepticism of US military action. South African media is among Africa's most independent and diverse, capable of producing sophisticated analysis critical of Western interventionism. ICJ genocide case against Israel in 2024 positioned South Africa as global voice for Global South critique of Western military policy. |
| Japan | allied | Treaty ally hosting 50,000 US military personnel, with security dependence creating strong institutional alignment with US positions on military action. Japanese media is professional and cautious, shaped by pacifist constitutional Article 9 tradition that makes public wary of endorsing military action even by allies. Coverage tends to emphasize energy security implications given Japan's near-total dependence on Middle Eastern oil. |
| Brazil | neutral | Regional power with tradition of non-intervention and multilateral diplomacy, historically skeptical of US unilateral military action. Brazilian media is diverse and commercially driven, with Globo dominant, and coverage tends toward sovereignty-focused framing critical of intervention. Lula's return to power reinforced Global South positioning and BRICS alignment that frames US military action as destabilizing. |
| United States | self | Principal actor in Middle East military operations, with deeply polarized domestic media ecosystem producing wildly different framings of same events. Conservative media (Fox, talk radio) tends toward hawkish support for military action especially against Iran, while progressive outlets emphasize civilian casualties and question strategic rationale. Post-Iraq media environment includes greater skepticism than pre-2003 but rally-round-the-flag effects still apply at conflict onset. |
| Turkey | complicated | NATO member that has increasingly charted independent foreign policy under Erdogan, purchasing Russian S-400 systems and opposing US support for Kurdish forces in Syria. Turkish media is largely controlled by Erdogan-aligned conglomerates, framing Turkey as independent regional power rather than Western subordinate. Opposes both Iranian expansion and US unilateralism, positioning as Sunni-world alternative leader. |
| Ireland | neutral | Militarily neutral with no NATO membership and strong historical anti-colonial identity that generates skepticism of Anglo-American military intervention. Shannon Airport's use for US military transit is domestically contentious and keeps US military policy in public discourse. Irish media draws on colonial experience to produce coverage sympathetic to populations subjected to military action. |

## Full Country List (58 countries)

**Middle East (14):** Iran, Israel, Saudi Arabia, Qatar, Egypt, Pakistan, Iraq, Turkey, UAE, Oman, Jordan, Lebanon, Syria, Yemen

**Europe (19):** United Kingdom, France, Germany, Spain, Italy, Netherlands, Belgium, Norway, Switzerland, Ireland, Czech Republic, Romania, Bulgaria, Croatia, Albania, Kosovo, Lithuania, Slovak Republic

**Asia (10):** China, India, Japan, South Korea, Singapore, Bangladesh, Indonesia, Hong Kong, Taiwan, Philippines

**Africa (4):** South Africa, Kenya, Nigeria, Uganda

**Latin America (5):** Brazil, Argentina, Mexico, Colombia, Venezuela

**North America (2):** United States, Canada

**Other (4):** Russia, Ukraine, Azerbaijan, Australia, New Zealand

## Relationship Distribution

| Relationship | Count |
|-------------|-------|
| allied | 28 |
| neutral | 10 |
| complicated | 8 |
| adversarial | 7 |
| self | 1 |
