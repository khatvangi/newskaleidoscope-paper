#!/usr/bin/env python3
"""
outlet_curator.py — curated registry of 40 flagship global news outlets.
outputs outlets.json with metadata for epistemic mapping.
"""

import json

OUTLETS = [
    # ── Middle East (6) ──────────────────────────────────────────
    {
        "name": "Al Jazeera",
        "domain": "aljazeera.com",
        "country": "Qatar",
        "region": "Middle East",
        "language": "English",
        "tier": 1,
        "bias_notes": "Qatar state-funded; critical of Saudi/UAE, sympathetic to Palestinian cause",
        "rss_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "free_access": True
    },
    {
        "name": "Haaretz",
        "domain": "haaretz.com",
        "country": "Israel",
        "region": "Middle East",
        "language": "English",
        "tier": 1,
        "bias_notes": "Israeli liberal-left; critical of Netanyahu government",
        "rss_url": "https://www.haaretz.com/cmlink/1.628765",
        "free_access": False
    },
    {
        "name": "Al-Monitor",
        "domain": "al-monitor.com",
        "country": "USA",
        "region": "Middle East",
        "language": "English",
        "tier": 1,
        "bias_notes": "US-based Middle East focused; centrist, policy-oriented",
        "rss_url": "https://www.al-monitor.com/rss",
        "free_access": True
    },
    {
        "name": "Arab News",
        "domain": "arabnews.com",
        "country": "Saudi Arabia",
        "region": "Middle East",
        "language": "English",
        "tier": 1,
        "bias_notes": "Saudi state-aligned; reflects Riyadh foreign policy positions",
        "rss_url": "https://www.arabnews.com/rss.xml",
        "free_access": True
    },
    {
        "name": "Al-Ahram",
        "domain": "english.ahram.org.eg",
        "country": "Egypt",
        "region": "Middle East",
        "language": "English",
        "tier": 1,
        "bias_notes": "Egyptian state-owned; reflects government positions",
        "rss_url": "",
        "free_access": True
    },
    {
        "name": "Dawn",
        "domain": "dawn.com",
        "country": "Pakistan",
        "region": "Middle East",
        "language": "English",
        "tier": 1,
        "bias_notes": "Pakistan's oldest English daily; editorially independent, liberal-leaning",
        "rss_url": "https://www.dawn.com/feeds/home",
        "free_access": True
    },

    # ── Europe (6) ───────────────────────────────────────────────
    {
        "name": "BBC News",
        "domain": "bbc.com",
        "country": "United Kingdom",
        "region": "Europe",
        "language": "English",
        "tier": 1,
        "bias_notes": "UK public broadcaster; centrist, occasionally criticized as establishment-aligned",
        "rss_url": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "free_access": True
    },
    {
        "name": "Le Monde",
        "domain": "lemonde.fr",
        "country": "France",
        "region": "Europe",
        "language": "French",
        "tier": 1,
        "bias_notes": "French center-left; strong editorial independence tradition",
        "rss_url": "https://www.lemonde.fr/rss/une.xml",
        "free_access": False
    },
    {
        "name": "Der Spiegel",
        "domain": "spiegel.de",
        "country": "Germany",
        "region": "Europe",
        "language": "German",
        "tier": 1,
        "bias_notes": "German center-left investigative; influential in EU policy circles",
        "rss_url": "https://www.spiegel.de/international/index.rss",
        "free_access": False
    },
    {
        "name": "El País",
        "domain": "elpais.com",
        "country": "Spain",
        "region": "Europe",
        "language": "Spanish",
        "tier": 1,
        "bias_notes": "Spanish center-left; largest Spanish-language quality daily",
        "rss_url": "https://feeds.elpais.com/mrss-s/pages/ep/site/english.elpais.com/portada",
        "free_access": True
    },
    {
        "name": "Corriere della Sera",
        "domain": "corriere.it",
        "country": "Italy",
        "region": "Europe",
        "language": "Italian",
        "tier": 1,
        "bias_notes": "Italian centrist establishment; Milan-based, business-oriented",
        "rss_url": "https://xml2.corriereobjects.it/rss/homepage.xml",
        "free_access": False
    },
    {
        "name": "The Guardian",
        "domain": "theguardian.com",
        "country": "United Kingdom",
        "region": "Europe",
        "language": "English",
        "tier": 1,
        "bias_notes": "UK center-left; strong on human rights, critical of military interventions",
        "rss_url": "https://www.theguardian.com/world/rss",
        "free_access": True
    },

    # ── Asia (8) ─────────────────────────────────────────────────
    {
        "name": "The Hindu",
        "domain": "thehindu.com",
        "country": "India",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "Indian center-left; Chennai-based, editorially independent",
        "rss_url": "https://www.thehindu.com/feeder/default.rss",
        "free_access": True
    },
    {
        "name": "Nikkei Asia",
        "domain": "asia.nikkei.com",
        "country": "Japan",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "Japanese business-focused; centrist, strong Asia economic coverage",
        "rss_url": "",
        "free_access": False
    },
    {
        "name": "South China Morning Post",
        "domain": "scmp.com",
        "country": "Hong Kong",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "Alibaba-owned; increasingly Beijing-aligned since 2016 acquisition",
        "rss_url": "https://www.scmp.com/rss/91/feed",
        "free_access": True
    },
    {
        "name": "Global Times",
        "domain": "globaltimes.cn",
        "country": "China",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "CPC-affiliated tabloid; nationalist, represents hawkish PRC positions",
        "rss_url": "",
        "free_access": True
    },
    {
        "name": "The Straits Times",
        "domain": "straitstimes.com",
        "country": "Singapore",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "Singapore state-linked via SPH Media Trust; pro-government, pragmatic",
        "rss_url": "",
        "free_access": False
    },
    {
        "name": "The Daily Star",
        "domain": "thedailystar.net",
        "country": "Bangladesh",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "Bangladesh independent; liberal, editorially critical of authoritarianism",
        "rss_url": "https://www.thedailystar.net/frontpage/rss.xml",
        "free_access": True
    },
    {
        "name": "The Jakarta Post",
        "domain": "thejakartapost.com",
        "country": "Indonesia",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "Indonesian English-language daily; centrist, moderate Islamic perspective",
        "rss_url": "https://www.thejakartapost.com/rss",
        "free_access": True
    },
    {
        "name": "The Korea Herald",
        "domain": "koreaherald.com",
        "country": "South Korea",
        "region": "Asia",
        "language": "English",
        "tier": 1,
        "bias_notes": "South Korean centrist; government-designated English daily",
        "rss_url": "http://www.koreaherald.com/common/rss_xml.php",
        "free_access": True
    },

    # ── Africa (4, Al-Ahram counted in Middle East) ──────────────
    {
        "name": "Daily Maverick",
        "domain": "dailymaverick.co.za",
        "country": "South Africa",
        "region": "Africa",
        "language": "English",
        "tier": 1,
        "bias_notes": "South African independent investigative; center-left, anti-corruption",
        "rss_url": "https://www.dailymaverick.co.za/dmrss/",
        "free_access": True
    },
    {
        "name": "Nation Africa",
        "domain": "nation.africa",
        "country": "Kenya",
        "region": "Africa",
        "language": "English",
        "tier": 1,
        "bias_notes": "East Africa's largest media group; centrist, commercially driven",
        "rss_url": "",
        "free_access": False
    },
    {
        "name": "Punch Nigeria",
        "domain": "punchng.com",
        "country": "Nigeria",
        "region": "Africa",
        "language": "English",
        "tier": 1,
        "bias_notes": "Nigeria's most widely read; independent, critical of government",
        "rss_url": "https://punchng.com/feed/",
        "free_access": True
    },
    {
        "name": "New Vision",
        "domain": "newvision.co.ug",
        "country": "Uganda",
        "region": "Africa",
        "language": "English",
        "tier": 1,
        "bias_notes": "Ugandan government-owned; reflects Museveni administration positions",
        "rss_url": "",
        "free_access": True
    },

    # ── Latin America (4) ────────────────────────────────────────
    {
        "name": "Folha de São Paulo",
        "domain": "folha.uol.com.br",
        "country": "Brazil",
        "region": "Latin America",
        "language": "Portuguese",
        "tier": 1,
        "bias_notes": "Brazil's largest circulation; center-right, business-oriented",
        "rss_url": "https://feeds.folha.uol.com.br/mundo/rss091.xml",
        "free_access": False
    },
    {
        "name": "El Espectador",
        "domain": "elespectador.com",
        "country": "Colombia",
        "region": "Latin America",
        "language": "Spanish",
        "tier": 1,
        "bias_notes": "Colombian liberal; oldest newspaper in Colombia, editorially independent",
        "rss_url": "https://www.elespectador.com/rss",
        "free_access": True
    },
    {
        "name": "La Jornada",
        "domain": "jornada.com.mx",
        "country": "Mexico",
        "region": "Latin America",
        "language": "Spanish",
        "tier": 1,
        "bias_notes": "Mexican left-wing; sympathetic to AMLO/Morena, anti-US foreign policy",
        "rss_url": "https://www.jornada.com.mx/rss/mundo.xml",
        "free_access": True
    },
    {
        "name": "Clarín",
        "domain": "clarin.com",
        "country": "Argentina",
        "region": "Latin America",
        "language": "Spanish",
        "tier": 1,
        "bias_notes": "Argentina's largest media group; center-right, anti-Kirchnerist",
        "rss_url": "https://www.clarin.com/rss/lo-ultimo/",
        "free_access": True
    },

    # ── North America (3, La Jornada counted in LatAm) ───────────
    {
        "name": "The New York Times",
        "domain": "nytimes.com",
        "country": "United States",
        "region": "North America",
        "language": "English",
        "tier": 1,
        "bias_notes": "US center-left establishment; paper of record, strong foreign desk",
        "rss_url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "free_access": False
    },
    {
        "name": "The Wall Street Journal",
        "domain": "wsj.com",
        "country": "United States",
        "region": "North America",
        "language": "English",
        "tier": 1,
        "bias_notes": "US center-right; Murdoch-owned, hawkish on foreign policy",
        "rss_url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
        "free_access": False
    },
    {
        "name": "The Globe and Mail",
        "domain": "theglobeandmail.com",
        "country": "Canada",
        "region": "North America",
        "language": "English",
        "tier": 1,
        "bias_notes": "Canadian centrist establishment; Toronto-based, business-leaning",
        "rss_url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/world/",
        "free_access": False
    },

    # ── Tier 2: Religious / Institutional (7) ────────────────────
    {
        "name": "Vatican News",
        "domain": "vaticannews.va",
        "country": "Vatican",
        "region": "Europe",
        "language": "English",
        "tier": 2,
        "bias_notes": "Official Vatican media; reflects Pope Francis positions on peace and dialogue",
        "rss_url": "https://www.vaticannews.va/en.rss.xml",
        "free_access": True
    },
    {
        "name": "Al-Azhar Observer",
        "domain": "azharobserver.com",
        "country": "Egypt",
        "region": "Middle East",
        "language": "English",
        "tier": 2,
        "bias_notes": "Al-Azhar University official; Sunni Islamic authority, moderate establishment",
        "rss_url": "",
        "free_access": True
    },
    {
        "name": "Arutz Sheva",
        "domain": "israelnationalnews.com",
        "country": "Israel",
        "region": "Middle East",
        "language": "English",
        "tier": 2,
        "bias_notes": "Israeli religious-nationalist right; settler movement affiliated",
        "rss_url": "https://www.israelnationalnews.com/Rss",
        "free_access": True
    },
    {
        "name": "Panchjanya",
        "domain": "panchjanya.com",
        "country": "India",
        "region": "Asia",
        "language": "Hindi",
        "tier": 2,
        "bias_notes": "RSS (Rashtriya Swayamsevak Sangh) affiliated; Hindu nationalist weekly",
        "rss_url": "",
        "free_access": True
    },
    {
        "name": "Christianity Today",
        "domain": "christianitytoday.com",
        "country": "United States",
        "region": "North America",
        "language": "English",
        "tier": 2,
        "bias_notes": "US evangelical Protestant; centrist-evangelical, editorially independent",
        "rss_url": "https://www.christianitytoday.com/feed/",
        "free_access": True
    },
    {
        "name": "Muslim World League Journal",
        "domain": "themwl.org",
        "country": "Saudi Arabia",
        "region": "Middle East",
        "language": "English",
        "tier": 2,
        "bias_notes": "Saudi-backed pan-Islamic body; reflects MBS-era moderate Islam messaging",
        "rss_url": "",
        "free_access": True
    },
    {
        "name": "Crux",
        "domain": "cruxnow.com",
        "country": "United States",
        "region": "North America",
        "language": "English",
        "tier": 2,
        "bias_notes": "Independent Catholic news; covers Vatican and global Catholic perspectives",
        "rss_url": "https://cruxnow.com/feed",
        "free_access": True
    },
]


def main():
    output_file = "outlets.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(OUTLETS, f, indent=2, ensure_ascii=False)

    # summary
    regions = {}
    tiers = {1: 0, 2: 0}
    for o in OUTLETS:
        regions[o["region"]] = regions.get(o["region"], 0) + 1
        tiers[o["tier"]] += 1

    print(f"[outlets] wrote {len(OUTLETS)} outlets to {output_file}")
    print(f"\n  by region:")
    for region, count in sorted(regions.items()):
        print(f"    {region}: {count}")
    print(f"\n  by tier:")
    print(f"    tier 1 (flagship): {tiers[1]}")
    print(f"    tier 2 (religious/institutional): {tiers[2]}")


if __name__ == "__main__":
    main()
