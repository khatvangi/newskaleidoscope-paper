# Table 1: Corpus Characteristics

| Characteristic | Iran Strike (CS1) | Ukraine Invasion (CS1-RU) |
|---|---:|---:|
| **Time window** | Feb 26 – Mar 6, 2026 | Feb 24 – Mar 2, 2022 |
| **Total articles ingested** | 1,267 | 2,096 |
| **Articles with extractable text** | 1,267 (100%) | 1,863 (88.9%) |
| **Unique news sources** | 330 | 717 |
| **Languages represented** | 24 | 41 |
| **Regions represented** | 9 | 9 |
| | | |
| **Source breakdown** | | |
| &emsp;GDELT DOC API | 121 (9.5%) | 1,944 (92.7%) |
| &emsp;World News API | 1,087 (85.8%) | 0 (0%)* |
| &emsp;Reddit (vernacular) | 109 (8.6%) | 152 (7.3%) |
| | | |
| **Text processing** | | |
| &emsp;Text extraction success | 100% | 86.2% |
| &emsp;Wayback Machine recoveries | N/A | 1,456 articles |
| &emsp;Translation success | 100% | 99.9% (1 failure) |
| | | |
| **Analysis** | | |
| &emsp;Pass 1 (framing extraction) | 1,267 | 1,863 |
| &emsp;Council validation | Full (3 models × 1,267) | Sample (2 models × 307) |
| &emsp;Emergent clusters | 119 | 93 |
| &emsp;Singletons | 76 | 68 |

\* World News API returned 0 results for 2022 historical date queries despite supporting date parameters in the API specification.
