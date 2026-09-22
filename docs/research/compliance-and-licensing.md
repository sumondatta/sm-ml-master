<!--
Compiled from a research sweep, not written by hand. Preserved verbatim because
it is reference material the implementation draws on rather than prose meant to
be read start to finish.

CONFIDENCE: the sweep's web-search budget was exhausted before these sections
ran, so everything in them is recalled from model knowledge and NONE of it was
corroborated by a search. Every URL and every accuracy figure must be verified
before it is relied on. Nothing here is legal advice.
-->

**CRITICAL CAVEAT — READ FIRST:** This session's WebSearch budget (200/200) was exhausted before I could issue a single query. **Every statement below is `[recalled]` from training (cutoff May 2026) and NOT confirmed by search.** Every URL must be verified before use. I have flagged the few items where I am genuinely unsure with `[unverified-URL]` or `[low confidence]`. Nothing here is legal advice; items marked **[COUNSEL]** cannot be resolved by web search at all.

---

# COMPLIANCE DESIGN: Soil-Moisture Literature Harvest + Figure Digitization + Open Database

---

## A. TDM LAW BY JURISDICTION

### A.1 EU — Directive (EU) 2019/790 (DSM Directive) `[recalled]`

**Art. 2(1) "TDM"** = any automated analytical technique aimed at analysing text and data in digital form to generate information including patterns, trends and correlations. Figure digitization from PDFs is squarely TDM.

**Art. 2(2) "research organisation"** = university (incl. its libraries), research institute, or other entity whose primary goal is scientific research, on a not-for-profit basis, reinvesting all profits in research, or under a public-interest mission recognised by a Member State. **A US university is not, on its face, an EU research organisation**, and Art. 3 applies to acts within Member States. If the copying servers are in the US, US law governs the copying. **[COUNSEL]** — territoriality/choice-of-law here is genuinely unsettled; if you have an EU co-PI, run the EU-side harvest on their infrastructure under their institution's name and the analysis is far cleaner.

**Art. 3** (mandatory, research orgs + cultural heritage institutions):
- Permits reproductions **and extractions from databases** for TDM **for scientific research**, of works to which they have **lawful access**.
- "Lawful access" (Recital 14) = subscription, open access, freely available online with rightholder consent, or other lawful means. Sci-Hub is not lawful access.
- **Copies MAY be retained** — Art. 3(2): stored "with an appropriate level of security" and retained "for the purposes of scientific research, including for the verification of research results." This is an explicit retention right, unusually generous.
- **Art. 7(1) makes contractual override unenforceable.** A publisher licence clause banning TDM is void against an EU research organisation.
- **Art. 3(3)** lets rightholders apply "measures to ensure the security and integrity of the networks and databases" — this is the legal basis for API-only access, rate limits, and token requirements. Publishers may throttle; they may not block outright.
- Art. 3 expressly disapplies Art. 7(1) of the Database Directive 96/9/EC (the sui generis extraction right) for research orgs.
- **No redistribution right.** Recital 15 permits sharing with "persons involved in the research" for verification. Public redistribution of the corpus is outside Art. 3.

**Art. 4** (general TDM, any purpose incl. commercial):
- Reproductions/extractions of **lawfully accessible** works, **unless expressly reserved by the rightholder in an appropriate manner** — for content made publicly available online, "by machine-readable means."
- Retention only "for as long as necessary for the purposes of TDM" — no indefinite corpus.
- **Overridable** by the reservation and by contract.
- How publishers express the Art. 4 reservation in practice: (i) robots.txt disallow + AI-bot user-agent blocks; (ii) **W3C TDM Reservation Protocol (TDMRep)** — `/.well-known/tdmrep.json`, HTTP header `TDM-Reservation: 1`, HTML `<meta name="tdm-reservation" content="1">`, https://www.w3.org/community/tdmrep/ and https://www.w3.org/2022/tdmrep/; (iii) ToS text (Recital 18 accepts website T&Cs as "appropriate" for online content); (iv) `ai.txt`; (v) the IETF **AI Preferences (aipref)** WG's `Content-Usage` signal `[low confidence on 2026 status]`.
- Your pipeline must **fetch, parse and log** TDMRep + robots.txt per domain and record the result in `terms_snapshot_hash`.

**EU plain answers:** retain corpus — **yes under Art. 3 for an EU research org; no indefinite retention under Art. 4**. Redistribute extracted numbers — **yes** (facts; see §C, subject to 96/9). Redistribute corpus — **no**.

### A.2 UK — CDPA 1988 s.29A `[recalled]`

Inserted by SI 2014/1372. "Copies for text and data analysis for non-commercial research."
- Conditions: (a) **lawful access**; (b) copy made to carry out **computational analysis** of anything recorded in the work; (c) **sole purpose of research for a non-commercial purpose**; (d) **sufficient acknowledgement** unless impracticable.
- **s.29A(2): the copy may NOT be transferred to another person** (except with the copyright owner's authorisation) and may not be used for any other purpose. Infringing transfer = the copy becomes an infringing copy.
- **s.29A(5): contractual override is unenforceable.**
- Narrower than EU Art. 3 in two ways that matter: **non-commercial only** (a spin-out or industry-funded phase kills it), and **no transfer even to research collaborators**.

2022–2026 trajectory `[recalled, verify]`: the IPO's June 2022 proposal for a broad all-purpose TDM exception with no opt-out was **abandoned in Feb 2023**; a voluntary code-of-practice process collapsed in Feb 2024; the **Dec 2024 "Copyright and AI" consultation** (closed 25 Feb 2025) proposed a commercial TDM exception with rights reservation + transparency; the **Data (Use and Access) Act 2025** (Royal Assent June 2025) added government reporting duties but **did not change s.29A**. Assume s.29A as written is still the law.

**UK plain answers:** retain — yes, for non-commercial research. Redistribute numbers — yes. Redistribute corpus — **no, explicitly barred by s.29A(2)**.

### A.3 Japan — Copyright Act Art. 30-4 `[recalled]`

2018 amendment, in force 1 Jan 2019. Permits exploitation of a work "in any way and to the extent deemed necessary" where the purpose is **not to enjoy, or cause another to enjoy, the thoughts or sentiments expressed** — with item (ii) expressly covering **data analysis** (extracting, comparing, classifying or statistically analysing language, sound, image or other elements from a large number of works). **Commercial use permitted; no opt-out mechanism.** The world's most permissive TDM rule.
- **Proviso:** not permitted where it would "unreasonably prejudice the interests of the copyright owner in light of the nature or purpose of the work or the circumstances of its exploitation." The Agency for Cultural Affairs' **March 2024 "General Understanding on AI and Copyright"** reads this to exclude: circumventing paywalls/technical measures; copying a database work that is itself **sold for TDM purposes**; and (contested) RAG-style systems that output substantial expression.
- Art. 47-5 permits minor/incidental use of works when providing analysis results.
- No redistribution right for the corpus.

### A.4 Singapore — Copyright Act 2021 (No. 22 of 2021), s.244 `[recalled]`

"Computational data analysis" permitted act. Copying for CDA (expressly including **machine learning / training**) and for preparing the work for CDA.
- Conditions: **lawful access** to the first copy (s.243/244 — circumventing a paywall or accessing in breach of ToS defeats it); the copy is **not used for any other purpose**; the copy is **not supplied to anyone else except for collaborative CDA on the same project, or for verification of results**.
- **Commercial use permitted. No opt-out. s.187 makes contractual override unenforceable.**
- Practically the best-drafted TDM exception in the world for a project like yours — if you have a Singapore collaborator (NUS/NTU/A*STAR), that is a legitimate place to site the corpus.

### A.5 US — no statutory TDM exception; 17 U.S.C. §107 fair use `[recalled]`

Favourable line:
- **Authors Guild v. HathiTrust**, 755 F.3d 87 (2d Cir. 2014) — mass digitization for full-text search = transformative, fair use.
- **Authors Guild v. Google**, 804 F.3d 202 (2d Cir. 2015), cert. denied 2016 — mass scanning + snippet display fair use; "non-expressive use."
- **A.V. v. iParadigms**, 562 F.3d 630 (4th Cir. 2009) — building a searchable database of student papers, fair use.
- **Sega v. Accolade**, **Sony v. Connectix** — intermediate copying to extract unprotected elements.

2023–2026 AI cases:
- **Thomson Reuters v. ROSS Intelligence**, No. 1:20-cv-613 (D. Del.), Bibas, J., revised SJ opinion **11 Feb 2025** — **NOT fair use**. Non-generative legal-research AI trained on Westlaw headnotes; factor one not transformative because ROSS built a market substitute; factor four decisive. Interlocutory appeal certified to the Third Circuit `[recalled, 2026 outcome unknown]`. **Read this as: the closer your output is to substituting for the source's own market, the worse your factor four.** Your output — a soil-moisture simulator — does not substitute for the market for journal articles. That is a strong distinction, and you should say so in writing in your DMP.
- **Bartz v. Anthropic**, No. 3:24-cv-05417 (N.D. Cal.), Alsup, J., **23–24 June 2025** — training LLMs on **lawfully purchased** books was "exceedingly transformative," fair use; but **downloading pirated copies to build a central library was NOT fair use** and went to trial; settled Sept 2025 for ~$1.5B (~$3,000/work × ~500,000 works). **This is the single most important case for your project: the dispositive issue was the method of acquisition, not the analysis.**
- **Kadrey v. Meta**, No. 3:23-cv-03417 (N.D. Cal.), Chhabria, J., **25 June 2025** — SJ for Meta on fair use because plaintiffs failed to build a market-dilution record, with the opinion expressly disclaiming any general holding and flagging market dilution as the likely winning theory.
- Ongoing: *NYT v. OpenAI & Microsoft* (S.D.N.Y. 1:23-cv-11195); *Getty v. Stability* (D. Del.; UK High Court judgment Nov 2025 largely failed on training because training occurred outside the UK) `[recalled]`.
- **Feist Publications v. Rural Telephone**, 499 U.S. 340 (1991) — facts uncopyrightable; **no sweat-of-the-brow**; compilations get only "thin" protection in original selection/arrangement.

Non-copyright US exposure:
- **CFAA** narrowed by **Van Buren v. United States**, 141 S. Ct. 1648 (2021) and **hiQ v. LinkedIn** (9th Cir. 2022) — ToS breach alone is not "exceeds authorized access." But credential sharing / paywall circumvention is different (cf. *United States v. Swartz*).
- **DMCA §1201** if you defeat any technical access control.
- **Breach of the library's licence agreement** is the real and near-certain risk. There is no US anti-override rule: **the contract wins over fair use in practice**, because the remedy (instant suspension of the whole campus's access) is self-executing and needs no court.

**US plain answers:** retain corpus — defensible under §107 if lawfully acquired, **but governed by the library licence**. Redistribute numbers — **yes** (Feist). Redistribute corpus — **no**.

---

## B. PUBLISHER MECHANICS

### B.1 The decisive strategic point

**Restructure the harvest so that ≥80% of the corpus is open access, and the publisher-TDM problem largely evaporates.** Soil moisture / irrigation / vadose zone literature is unusually OA-rich: Copernicus (HESS, SOIL, ESSD, Biogeosciences — all CC-BY-4.0), MDPI (*Water*, *Remote Sensing*, *Agronomy*, *Sensors* — CC-BY), Frontiers, PLOS, ASA-CSSA-SSSA's *Vadose Zone Journal* and *Agronomy Journal* (hybrid, growing OA share), *Agricultural Water Management* (Elsevier, substantial OA), AGU journals (*WRR*, *JGR* — Wiley, large CC-BY share since the 2023 AGU OA transition) `[recalled]`. Plus Plan S **rights-retention** accepted manuscripts sitting in institutional repositories under CC-BY.

**Open-first harvest stack (use these before touching a publisher API):**

| Source | Endpoint `[recalled URLs — verify]` | What you get |
|---|---|---|
| **OpenAlex** | `https://api.openalex.org/works?filter=...&mailto=you@univ.edu`; full snapshot `s3://openalex` (CC0) | Best discovery layer; free, no key, CC0 metadata |
| **Crossref REST** | `https://api.crossref.org/works?query.bibliographic=...&mailto=...` | DOIs, licences, `link` elements, funders |
| **Unpaywall** | `https://api.unpaywall.org/v2/{doi}?email=you@univ.edu`; free bulk snapshot | Legal OA copy locator |
| **PMC OA Subset** | FTP `https://ftp.ncbi.nlm.nih.gov/pub/pmc/` (oa_comm / oa_noncomm / oa_other); OA Web Service `https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/`; **AWS open bucket `s3://pmc-oa-opendata`** | JATS XML **+ the separate figure image files** — exactly what a digitizer needs, with clean per-article licences |
| **Europe PMC** | `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=...&format=json`; full text `.../{PMCID}/fullTextXML`; supplementary-files endpoint | Broader than PMC; annotations API |
| **CORE** | `https://api.core.ac.uk/v3/` (free key); bulk dataset for research | 300M+ OA full texts incl. repository AAMs |
| **Semantic Scholar / S2ORC** | `https://api.semanticscholar.org/graph/v1/`; S2ORC bulk under agreement | Parsed full text |
| **DOAJ** | `https://doaj.org/api/v3/` | Confirms journal-level licence |
| **DataCite** | `https://api.datacite.org/dois?query=...` — `rightsList` field | **Machine-readable licence per deposited dataset** — the highest-yield route to raw data, not digitized data |

### B.2 Per-publisher TDM mechanics `[all recalled — verify every URL and every quota]`

**Elsevier**
- Policy: `https://www.elsevier.com/about/policies-and-standards/text-and-data-mining`
- Dev portal / key: `https://dev.elsevier.com/`, `https://dev.elsevier.com/apikey/manage`
- Article Retrieval (full text): `https://api.elsevier.com/content/article/doi/{doi}` (also `/pii/{pii}`, `/eid/{eid}`, `/pubmed_id/{pmid}`)
- ScienceDirect Search v2: `https://api.elsevier.com/content/search/sciencedirect` (PUT with JSON body)
- Scopus Search: `https://api.elsevier.com/content/search/scopus`
- Auth headers: **`X-ELS-APIKey`** and, for off-campus/full-text entitlement, **`X-ELS-Insttoken`** (institutional token — your librarian requests it from Elsevier support; it is not self-service)
- Content negotiation: `Accept: text/xml` (full-text XML is what you get for TDM), `application/json`. **PDF retrieval via the TDM API is generally not granted** — plan for JATS/Elsevier-XML, which is better anyway.
- Quotas `[verify at https://dev.elsevier.com/api_key_settings.html]`: Article Retrieval ~**10,000 requests/week, 10 req/s**; Scopus Search ~20,000/week, 9 req/s.
- **API-not-scraping is mandatory**: sciencedirect.com robots.txt disallows article paths and the licence bans "systematic downloading" / robots / spiders.
- Historic policy required TDM **output** (e.g. snippets ≤200 characters) to be licensed **CC-BY-NC** — if that clause survives, it is a contamination vector for your outputs. **Check the current text; this is a specific thing to ask the librarian.**

**Wiley**
- Policy: `https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining`
- Token: a **Wiley TDM Client Token** issued from that page to a subscribing institution's user.
- Endpoint: `https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}` with header **`Wiley-TDM-Client-Token: <token>`**; returns a 302 to the PDF.
- Rate `[low confidence]`: ~3 req/s, 60/min. Throttle to 1 req/s regardless.
- Terms: non-commercial research; no redistribution of content.

**Springer Nature**
- Policy: `https://www.springernature.com/gp/researchers/text-and-data-mining`
- API portal: `https://dev.springernature.com/`; base `https://api.springernature.com/`
- Open Access full text: `https://api.springernature.com/openaccess/jats?q=doi:{doi}&api_key=...` and `/openaccess/json`
- Metadata: `https://api.springernature.com/meta/v2/json?q=...&api_key=...`
- Subscribed full text requires a **negotiated institutional TDM agreement**; free-tier limits are small (order 500/day) `[verify]`.

**Others** `[all recalled, verify]`
- **Taylor & Francis**: `https://taylorandfrancis.com/partnership/commercial/text-and-data-mining/` — request-based; historically routed via Crossref TDM.
- **Sage**: TDM request form under `https://us.sagepub.com/`; agreement required.
- **ACS**: restrictive; requires a signed TDM agreement via `https://pubs.acs.org/page/copyright/permissions.html`. Low value for you — deprioritize.
- **IEEE**: `https://developer.ieee.org/` gives an **OA-metadata** API; full-text TDM needs a separate IEEE agreement. Low value here.
- **MDPI / Frontiers / PLOS / Copernicus**: fully OA, **CC-BY-4.0**, no TDM agreement needed. Copernicus and PLOS serve clean XML; MDPI and Frontiers are mirrored in **PMC/Europe PMC** — harvest from PMC, not from their websites, to avoid Cloudflare and to get a clean licence string.
- **AGU/Wiley, ASA/CSSA/SSSA (Wiley), ASABE, ASCE**: mixed; ASABE and ASCE are small closed corpora — consider one-off permission letters rather than an API.

### B.3 Crossref TDM click-through — current status `[recalled]`

The **Crossref Text and Data Mining click-through service** (`clickthrough.crossref.org`, the CRTDM licence-token flow) **was deprecated and retired** (announced ~2020, sunset ~2021–22). **Nothing replaced it.** Crossref's position is now: go to the publisher directly. Do not build against it.

**However, Crossref `link` and `license` elements are still deposited and still populated** — in the REST API:
```
"link":    [{"URL": "...", "content-type": "application/pdf",
             "content-version": "vor", "intended-application": "text-mining"}]
"license": [{"URL": "http://creativecommons.org/licenses/by/4.0/",
             "content-version": "vor", "start": {...}, "delay-in-days": 0}]
```
Coverage is patchy and inconsistent by publisher, and `intended-application: text-mining` links usually resolve to a token-gated or paywalled endpoint. **Use the `license` element as your primary machine-readable licence signal** (it is the field that tells you an article is CC-BY without you having to parse the PDF) and treat `link` as a best-effort hint.

### B.4 Pirate mirrors — explicitly out of scope

Sci-Hub, LibGen, Anna's Archive, Z-Library: **categorically excluded.** They defeat "lawful access" under EU Art. 3, UK s.29A, and SG s.244; they fall within the ACA proviso in Japan; and in the US *Bartz* priced pirated acquisition at $3,000/work while holding the downstream analysis fair use. They would also make the dataset undepositable and the papers unpublishable. Write this into the project's written policy, and put a **domain allowlist** in the crawler so it is architecturally impossible, not just prohibited.

### B.5 Recommended operational posture

1. **Named human owner** of the harvest, and a documented **kill switch**.
2. Route everything through the **scholarly communications / licensing librarian**, who holds the signed publisher agreements (these are usually confidential — you cannot find the terms by searching).
3. Obtain **written TDM permission per publisher** before the first bulk request. A one-paragraph email describing scope, volume, rate, and purpose is usually enough and takes 2–6 weeks.
4. **APIs and institutional tokens only.** No HTML scraping of publisher sites, ever.
5. **Throttle to 1 req/s per publisher**, hard nightly cap well under the stated quota, exponential backoff on 429/503, and stop-on-403.
6. **User-Agent:** `SoilMoistureTDM/0.1 (+https://<lab-url>/tdm-policy; mailto:sumondatta1991@gmail.com or institutional address)` — and host a real page at that URL describing the project, the rate policy, and an opt-out contact.
7. **Run from a dedicated static IP / VM, not the general campus range**, and tell the library's IT the IP, so a mistake blocks one VM rather than suspending the university's Elsevier access. *This is the single highest-value operational control in this document.*
8. **Log every request**: URL, DOI, timestamp, status, bytes, UA, and the robots/TDMRep decision. This log is your evidence of good faith.
9. Fetch and hash **robots.txt + `/.well-known/tdmrep.json` + the ToS page** per domain per quarter → `terms_snapshot_hash`.

---

## C. COPYRIGHT STATUS OF DIGITIZED FIGURE DATA — the crux

### C.1 United States: the numbers are free

**Feist**, 499 U.S. 340 (1991): facts are not copyrightable no matter how much labour went into collecting them; **sweat-of-the-brow is expressly rejected**. A soil-moisture time series plotted in a figure is a set of measurements — facts. Reconstructing those values from the plot yields facts. **They are freely redistributable in the US.** You also have an independent-creation argument: your digitized values are your own measurement of a public display, not a copy of the author's file.

Copyright subsists in the figure's *expression* — layout, colour choices, annotation, arrangement of panels — and, thinly, in your own selection/arrangement of the compilation (which you may license).

### C.2 EU/UK: sui generis database right — Directive 96/9/EC

- Art. 7(1): the **maker** who shows **substantial investment in obtaining, verifying or presenting** the contents may prevent extraction/re-utilisation of the whole or a **substantial part** (qualitative or quantitative).
- **British Horseracing Board v. William Hill, C-203/02 (ECJ, 9 Nov 2004)** — the decisive case, and it is in your favour: **"obtaining" means obtaining *pre-existing independent* materials, not *creating* them.** Investment in *generating* the data does not count. Confirmed by *Fixtures Marketing*, C-46/02, C-338/02, C-444/02 (same day). **A researcher who measured soil moisture and plotted it created the data — so an individual paper's figure is very unlikely to attract a sui generis right at all.**
- **Art. 7(5)** bans "repeated and systematic extraction and/or re-utilisation of insubstantial parts … which conflict with a normal exploitation of that database or which unreasonably prejudice the legitimate interests of the maker." BHB read this as aimed at **cumulative reconstitution of the whole or a substantial part of one database.** Taking one figure each from 50,000 *different* papers reconstitutes no single database. **Low risk.**
- The *publisher's own journal corpus*, by contrast, plausibly **is** a protected database (investment in obtaining, verifying, presenting others' articles). Systematic full-text extraction from it could touch Art. 7(5). Mitigations: **Art. 3 DSM disapplies 96/9 Art. 7(1) for research organisations**; 96/9 Art. 8 gives a lawful user the right to extract insubstantial parts, **non-overridable by Art. 15**.
- **Ryanair v. PR Aviation, C-30/14 (2015)** — a warning: where a database is *not* protected by copyright or sui generis right, the owner **may still restrict use by contract**, and Art. 8/15 protections do not apply. So "no database right" does not mean "no ToS problem."
- **CV-Online Latvia v. Melons, C-762/19 (2021)** — the right must be balanced against free flow of information; only conduct risking deprivation of the maker's investment income is caught.
- **UK post-Brexit:** the right continues domestically under the Copyright and Rights in Databases Regulations 1997 as amended by SI 2019/605; UK-made and EEA-made databases no longer get reciprocal protection for post-IP-completion-day databases.

### C.3 The figure *image* is a different question

Reproducing the **bitmap or vector figure** is a reproduction of a protected graphic work (owned by the publisher for subscription journals; CC-licensed for OA).

- **QC screenshots in your methods paper:** covered in the US by fair use (transformative, criticism/comment, tiny amount, no market harm) and in the EU/UK by the quotation exception (InfoSoc Art. 5(3)(d); UK CDPA ss.30(1ZA)/30(1); DE §51 UrhG). Also: the **STM Permissions Guidelines** (`https://www.stm-assoc.org/intellectual-property/permissions/permissions-guidelines/`) let signatory publishers' content be reused free for **up to 3 figures per article** in another publication `[recalled]` — cite this in your permissions request. **Good for a handful of examples in a paper; NOT for a public image repo.**
- **Training a chart-derendering model on figure crops:** this is TDM. EU Art. 3 covers it for an EU research org; US relies on fair use (post-*Bartz*, training on lawfully acquired material is strongly favoured). But **do not ship the training image set**.
- **Strong recommendation:** train the vision model on (i) **synthetically rendered charts** (you render matplotlib/plotly from known arrays → perfect ground truth, zero legal exposure — this is standard practice, cf. the DVQA / FigureQA / PlotQA / ChartQA / DePlot–MatCha pipelines), plus (ii) **PMC OA CC-BY figure images** (the OA subset ships the figure files separately — this is the legally clean real-figure source). Then the weights are unencumbered and you can release them.

### C.4 The technical move that solves most of this at once

**Most modern journal figures are vector, not raster.** Extract the polyline coordinates directly from the PDF content stream and the axis tick labels from the text layer — you get **near-exact numeric values with no CV, no rasterization, and no image ever stored.**

- `pdfplumber` (**MIT**) — `page.lines`, `page.curves`, `page.rects`, `page.chars`
- `pypdfium2` (**BSD-3 / Apache-2.0**)
- **Avoid `PyMuPDF` (AGPL-3.0)** in a pipeline you intend to release permissively — this is a real licence-contamination vector for your *code* that nobody flagged.
- Raster fallback: `pdffigures2` (Allen AI, Apache-2.0) for figure detection; `metaDigitise` (R, GPL) if you want inter-operator repeatability statistics, which reviewers of a data paper will ask for; WebPlotDigitizer for manual QC (**note: WPD v4 was AGPL-3.0; v5 moved to a commercial model at automeris.io** `[verify before relying on it]`).
- Record `digitization_rmse_vs_axis_ticks` — re-digitize the axis tick marks themselves and report the reconstruction error. This is the QC metric that will get the data paper accepted.

### C.5 Clear yes/no for publication

| Artifact | Publish? | Basis |
|---|---|---|
| **Numbers + citation + provenance** | **YES** | US: facts, *Feist*. EU/UK: BHB makes sui generis unlikely on individual papers; Art. 7(5) not triggered by one-figure-per-paper. Always attribute. **Except** where a contract/DUA (not copyright) restricts — see §D. |
| **Figure bitmaps / vector crops** | **NO** — except CC-BY / CC0 / PD sources, with attribution | Reproduction of a protected graphic work. Ship **figure locators** instead: `source_doi + figure_number + panel + page + bbox_pdfpts + image_sha256`, plus the extraction code. |
| **PDF / XML corpus** | **NO. Never.** | Barred under every regime and every contract. Ship the DOI list + retrieval script. |
| **Soil-moisture ML model weights (trained on numbers)** | **YES** | Trained on facts; no protected expression in the weights. |
| **Chart-derendering vision-model weights** | **YES if** trained only on synthetic + CC-licensed figures. Defensible but not certain if trained on subscription figure crops — so don't. | *Bartz*/*Kadrey* favourable but unsettled; the synthetic route removes the question entirely. |

**EU AI Act note:** Art. 53(1)(c)–(d) GPAI copyright-policy and training-data-summary obligations apply to general-purpose AI models — a task-specific soil-moisture regressor is not one, and Annex III high-risk categories do not cover agriculture. **Out of scope, but say so explicitly in the DMP so reviewers don't raise it.**

---

## D. LICENCE COMPOSITION AND CONTAMINATION

### D.1 Per-source matrix `[all recalled — verify every licence before ingesting]`

**T0 = public domain/CC0 · T1 = open, attribution · T2 = NC or share-alike (segregate) · T3 = pointer-only, do not redistribute**

| Source | Access | Licence | Redist.? | Tier | Notes |
|---|---|---|---|---|---|
| **ISMN** `https://ismn.earth` | Free registration | Custom **ISMN Data Policy**; per-network heterogeneity; some networks require PI contact | **NO** | **T3** | Must cite Dorigo et al. 2011 (HESS), 2011 (VZJ), **2021 (HESS)** *and* each contributing network. Policy directs third parties back to ISMN rather than permitting redistribution. `ismn` Python pkg reads the zip. **Email the ISMN team at TU Wien — they are collaborative, and a written carve-out is plausible.** |
| **AmeriFlux BASE** `https://ameriflux.lbl.gov/data/data-policy/` | Free account | **CC-BY-4.0** since Nov 2021 | **YES** | T1 | Cite site DOI + PI + funding; informing PIs and offering co-authorship are norms, not conditions. Vars: `SWC_1_1_1`…(`_H_V_R` indexing), `TS_*`, `P`, `LE`, `H`, `G`, `TA`, `VPD`, `SW_IN`. |
| **FLUXNET2015** | Account | **Tier 1 = CC-BY-4.0**; **Tier 2 = DUA, non-redistributable** | Tier 1 yes | T1/T3 | Split by tier at ingest. |
| **ICOS Carbon Portal** | Open | CC-BY-4.0 | YES | T1 | European counterpart. |
| **USDA-ARS Ag Data Commons** `https://agdatacommons.nal.usda.gov/` | Open | **US Gov work / CC0** (17 U.S.C. §105) | YES | **T0** | Includes the ARS Experimental Watershed Network: Walnut Gulch, **Little Washita & Fort Cobb (OK)**, Reynolds Creek, Little River (GA), South Fork (IA). |
| **USDA LTAR network** `https://ltar.ars.usda.gov/` | Open | US Gov / CC0 | YES | T0 | **Includes irrigated LTAR sites.** High priority. |
| **NRCS SCAN + AWDB** | Open | **US Gov, public domain** | YES | **T0** | REST API `https://wcc.sc.egov.usda.gov/awdbRestApi/` (Swagger UI at `/swagger-ui.html`) — legacy SOAP WSDL at `/awdbWebService/services?WSDL` `[verify which is live in 2026]`. Elements `SMS` (soil moisture %) at heightDepth −2, −4, −8, −20, −40 in; `STO` soil temp. ~200 mostly-agricultural stations, hourly, 5 depths. **Backbone of the open core.** |
| **Oklahoma Mesonet** `https://www.mesonet.org/` | Registration / data-request | Data Access Policy; OK public+educational free; out-of-state/bulk needs an agreement; commercial via OK Climatological Survey | **NO w/o agreement** | **T3** | Soil moisture from **229L matric-potential sensors → fractional water index**, 5/25/60/75 cm. Flag `sensor_type='Watermark_matric'` and `calibration='soil_specific'` — this is a modelling landmine, not just a licence one. |
| **Nebraska Mesonet / NAWMN** `https://mesonet.unl.edu/` | Request | Research use; redistribution by permission | **NO w/o permission** | **T3** | **The most important irrigated-field source in the US** (largest centre-pivot area). Treat as a **collaboration**, not a download. |
| **Kansas Mesonet, TexMesonet, West Texas Mesonet, AZMET, CoAgMet, WA AgWeatherNet, CA CIMIS** | Registration/API key | Mostly "free, research use, ask before redistributing" | Mixed | T1/T3 | CIMIS `https://cimis.water.ca.gov/` (API key) — ET, not SM, but ET is your irrigation driver. |
| **COSMOS-UK via UKCEH EIDC** `https://catalogue.ceh.ac.uk/` | Open | **Open Government Licence v3** (`https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/`) — CC-BY-compatible | **YES** | T1 | CRNS field-scale VWC + multi-depth point probes; annual DOI'd releases. Excellent. |
| **TERENO / TEODOOR** `https://www.tereno.net/`, `https://teodoor.icg.kfa-juelich.de/` | Registration | Per-observatory; citation + sometimes PI contact | Mixed | T2/T3 | Some TERENO data are mirrored in **PANGAEA under CC-BY** — prefer that copy. |
| **OzNet** `http://www.oznet.org.au/` | Registration | Research use, cite Smith et al. 2012 WRR | Unclear | T3 until confirmed | Ask Jeff Walker directly. |
| **TERN / OzFlux / CosmOz (CSIRO)** `https://www.tern.org.au/`, `https://cosmoz.csiro.au/` | Open | **CC-BY-4.0** | YES | T1 | Strong open Australian source. |
| **National Tibetan Plateau Data Center** `https://data.tpdc.ac.cn/` | Registration | **Per record** — many CC-BY-4.0 with an added data-use statement; some "application required" | Per record | T1/T3 | **HiWATER / Heihe (Zhangye oasis) = irrigated maize with dense multi-depth SM.** High value. Parse the per-record licence string; do not assume. |
| **CERN / CNERN (China)** `http://www.cnern.org.cn/` | Application per dataset | Chinese-language terms; research use; no redistribution | **NO** | **T3** | Also: **US export-control / research-security review** before any formal collaboration. **[COUNSEL]** |
| **Copernicus / ECMWF ERA5 & ERA5-Land** `https://cds.climate.copernicus.eu/` | Free account + token; `cdsapi` client against `https://cds.climate.copernicus.eu/api` | **"Licence to use Copernicus Products"** — free, worldwide, royalty-free, non-exclusive, **any lawful purpose incl. commercial, with the right to reproduce, distribute, modify and create derivatives** | **YES** | T1 | Attribution: *"Generated using Copernicus Climate Change Service information [year]"* + the non-responsibility disclaimer. Vars: `swvl1–4` (0–7/7–28/28–100/100–289 cm), `stl1–4`, `t2m`, `d2m`, `tp`, `e`, `pev`, `ssrd`, `strd`, `u10`, `v10`; 0.1°, hourly, 1950–present. **This is the gridded backbone and it is fully redistributable — unusually good.** |
| **ESA CCI Soil Moisture** `https://climate.esa.int/en/projects/soil-moisture/`; also on CDS | Free account | Free + citation (Gruber et al. 2019 ESSD; Dorigo et al. 2017 RSE) | YES w/ attribution | T1 | |
| **Copernicus Global Land SSM 1 km** `https://land.copernicus.eu/` | Free account | Copernicus terms | YES | T1 | Sentinel-1 based. |
| **NASA Earthdata** (SMAP SPL3SMP / SPL3SMP_E / **SPL4SMGP, SPL4SMAU** root-zone; NLDAS-2; GLDAS; MERRA-2; IMERG; MODIS; ECOSTRESS) | Free **Earthdata Login**; `earthaccess` lib; CMR `https://cmr.earthdata.nasa.gov/search/`; OPeNDAP/Harmony; S3 in us-west-2 | **Open, no restriction** ("NASA data are not copyrighted") | **YES** | **T0** | Login is an access gate, not a licence restriction. **SMAP L4 gives 0–5 cm and 0–100 cm at 9 km 3-hourly — directly relevant.** |
| **SMAP-HydroBlocks** (Vergopolan et al., 30 m) | Zenodo | CC-BY-4.0 | YES | T1 | |
| **USGS / Landsat** | Open | Public domain | YES | T0 | |
| **Zenodo** `https://zenodo.org/api/records`; OAI-PMH `https://zenodo.org/oai2d` | Open | **Per record** (CC0 / CC-BY / CC-BY-NC / restricted) | Per record | T0–T3 | Parse the `rights` field; never assume. |
| **Dryad** `https://datadryad.org/api/v2/` | Open | **CC0-1.0 mandated for all data** | YES | **T0** | Citation is a norm, not a condition. |
| **figshare** `https://api.figshare.com/v2/` | Open | Per item; commonly CC-BY-4.0 (data) / CC0 | Per item | T0–T2 | |
| **Mendeley Data** | Open | Per item; commonly CC-BY-4.0 | Per item | T1 | |
| **PANGAEA** `https://www.pangaea.de/`; `pangaeapy` | Open | Mostly **CC-BY-4.0**, some CC-BY-NC, some embargoed | Mostly yes | T1/T2 | Machine-readable licence per dataset. |
| **ESSD data papers** (Copernicus, ISSN 1866-3516) | Open | CC-BY-4.0 paper + a DOI'd open dataset each | YES | T1 | **Highest-yield single source of clean, curated, open soil-moisture data. Mine this first, before any digitization.** |
| **OpenET** `https://openetdata.org/`, API `https://openet-api.org/` (key) | Key, rate-limited | `https://openetdata.org/terms-of-use/` — attribution; **bulk raster redistribution likely restricted** `[verify]` | Point extracts likely yes | T1/T2 | Best available proxy for applied irrigation. |
| **Irrigation masks**: USDA **NASS CDL** `https://nassgeodata.gmu.edu/CropScape/` (**PD**); **LANID** (Xie & Lark, 30 m CONUS); **IrrMapper** (Ketchum et al., 11 western states); **MIrAD-US** (USGS, 250 m); **GFSAD30** (NASA); FAO **GMIA/AQUASTAT** (FAO CC-BY-4.0 `[verify]`) | Open | Mostly PD/CC-BY | YES | T0/T1 | **This is how you satisfy the "irrigated fields only" requirement at scale** — the `irrigated_bool` + `irrigation_evidence` columns. |
| **SSURGO / gNATSGO via Soil Data Access** `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest` (SQL over SSURGO!) | Open | **US Gov, public domain** | YES | **T0** | Horizon-resolved sand/silt/clay, BD, Ksat, `wthirdbar` (FC), `wfifteenbar` (WP), AWC. **The correct US soil-texture covariate — PD and horizon-resolved, unlike SoilGrids.** |
| **SoilGrids 2.0 (ISRIC)** `https://maps.isric.org/`; point REST `https://rest.isric.org/soilgrids/v2.0/properties/query?lon=..&lat=..&property=clay&depth=0-5cm&value=mean` | Open | **CC-BY-4.0 in v2.0** — **but earlier versions were ODbL** ⚠️ | YES if CC-BY | T1 | **Verify the version's licence before ingesting. This is exactly the contamination trap.** |
| **WoSIS (ISRIC)** | Open | CC-BY-4.0 | YES | T1 | Profile-level lab data. |
| **POLARIS** (30 m CONUS, Chaney et al.) `http://hydrology.cee.duke.edu/POLARIS/` | Open | No explicit licence; SSURGO-derived | Probably | T1 `[verify]` | |
| **HWSD v2 (FAO/IIASA)** | Open | FAO CC-BY-4.0 `[verify — historically custom terms]` | Probably | T1 | |
| **OpenLandMap** | Open/GEE | **Some layers CC-BY-SA-4.0** ⚠️ | Share-alike | **T2 — segregate** | |
| **ESDAC (JRC European Soil Data Centre)** | Signed request form | **No redistribution** for many layers | **NO** | **T3** | |
| **OpenStreetMap** (canals, field boundaries) | Open | **ODbL-1.0** ⚠️⚠️ | Share-alike, viral to derivative databases | **T2 / avoid** | **Do not join OSM into the main table.** |
| **Google Earth Engine** `https://earthengine.google.com/terms/` | Free for research; **commercial requires Earth Engine on Google Cloud (paid, GA 2023)** | **GEE is not a licence.** Per-dataset Terms of Use in the Data Catalog control. No mirroring/substitute-service. | Governed by source dataset | — | **RULE: never record "GEE" as a licence. Use GEE for point extraction, then attribute each extracted column to its underlying dataset's SPDX id.** |

### D.2 The composition answer

**With CC-BY, CC-BY-NC, ODbL and public-domain rows in one table, the union can only carry the most restrictive licence — which, if ODbL and NC are both present, is *nothing coherent at all*: ODbL's share-alike and CC-BY-NC are mutually incompatible.** Specifically:

- **CC0 / PD + CC-BY** → compose fine → release **CC-BY-4.0** with a full attribution manifest. (CC-BY-4.0 is one-way compatible into CC-BY-SA-4.0; nothing comes back.)
- **Add any CC-BY-NC row** → the whole table becomes NC. NC blocks commercial reuse, which for an agricultural-technology dataset is a large fraction of the intended impact, and the boundary of "non-commercial" is notoriously ill-defined.
- **Add any ODbL row** → your table becomes a **Derivative Database** under ODbL §4.4 and must be licensed ODbL. ODbL's "Produced Work" carve-out means *outputs* (a paper, a map, arguably model predictions) need only a notice — but the *table* is stuck. ODbL is incompatible with both CC-BY-SA and CC-BY-NC.
- **Add any DUA/pointer-only row (ISMN, OK/NE Mesonet, ESDAC, FLUXNET Tier 2, CNERN)** → you cannot publish those values *at all*, regardless of the licence you choose.

**Therefore there is exactly one workable architecture: per-row licensing with a physically tiered release.** Do not attempt to relicense the union. Do not "just use CC-BY and hope."

Secondary point worth stating in your data paper: in the US, a database of facts has **no copyright to license at all** (*Feist*). Your "licence" on the open core is doing three different jobs — (i) licensing the *thin* compilation copyright and any EU database right, (ii) licensing the schema/docs/code, (iii) stating a **norm** of attribution. Be explicit about which is which; the Panton Principles / Dryad approach is **CC0 for data + a separate community norms statement**, which avoids attribution-stacking. But **if any ingested row is CC-BY, you must pass BY through**, so CC-BY-4.0 is your realistic open-core licence.

### D.3 Required schema (exact columns)

**`source` table — one row per source (paper, network, gridded product):**

```
source_id                 TEXT PK        -- ULID
source_type               ENUM           -- literature_figure | literature_table | in_situ_network
                                         -- | repository_dataset | gridded_product | government_service
source_doi                TEXT
source_url                TEXT
source_citation           TEXT           -- formatted
source_bibtex             TEXT

-- digitization provenance (literature_figure only) — NO IMAGE STORED
figure_number             TEXT
figure_panel              TEXT
figure_page               INT
figure_bbox_pdfpts        REAL[4]        -- x0,y0,x1,y1 locator, not content
figure_image_sha256       TEXT           -- integrity/dedup only
extraction_method         ENUM           -- pdf_vector_path | WebPlotDigitizer_manual
                                         -- | metaDigitise | custom_cv | vlm_assisted
extraction_tool_version   TEXT
extractor                 TEXT           -- person ORCID or model id
extraction_date           DATE
n_axis_calibration_points INT
digitization_rmse_axis    REAL           -- reconstruction error on known tick marks
extraction_qc_status      ENUM           -- pass | flagged | rejected
second_extractor_agreement REAL          -- inter-operator repeatability

-- LICENCE BLOCK (the columns the task specified, plus what you actually need)
licence_spdx              TEXT NOT NULL  -- strict SPDX id, or LicenseRef-* for custom:
                                         -- CC0-1.0 | CC-BY-4.0 | CC-BY-NC-4.0 | ODbL-1.0
                                         -- | OGL-UK-3.0 | LicenseRef-USGov-PD
                                         -- | LicenseRef-Copernicus-LTU
                                         -- | LicenseRef-ISMN-DataPolicy-2024
                                         -- | LicenseRef-AmeriFlux-CCBY4
                                         -- | LicenseRef-OkMesonet-DUA
                                         -- | LicenseRef-Facts-Feist   (digitized numbers)
licence_url               TEXT NOT NULL
licence_verbatim_text     TEXT           -- store it; publishers change terms silently
terms_snapshot_hash       TEXT NOT NULL  -- SHA-256 of the fetched terms page
terms_snapshot_path       TEXT           -- WARC/HTML kept in the audit store
terms_retrieved_at        TIMESTAMPTZ NOT NULL
redistributable_bool      BOOLEAN NOT NULL
redistributable_basis     ENUM           -- licence | facts_not_copyrightable
                                         -- | us_gov_work | written_permission
redistribution_tier       ENUM NOT NULL  -- T0_public_domain | T1_attribution
                                         -- | T2_nc_or_sharealike | T3_pointer_only
commercial_use_bool       BOOLEAN
sharealike_bool           BOOLEAN
derivatives_bool          BOOLEAN
attribution_string        TEXT NOT NULL  -- exact credit line, ready to concatenate
required_citations        TEXT[]         -- DOIs that MUST be cited
notify_provider_bool      BOOLEAN
provider_contact_email    TEXT
notification_sent_at      TIMESTAMPTZ
permission_record_id      TEXT           -- FK to the signed permission / email thread

-- retrieval audit
retrieved_at              TIMESTAMPTZ NOT NULL
retrieval_endpoint        TEXT
retrieval_http_status     INT
retrieval_user_agent      TEXT
robots_decision           ENUM           -- allowed | disallowed | not_applicable
tdmrep_reservation        BOOLEAN        -- Art. 4 opt-out detected

-- integrity lifecycle
retracted_bool            BOOLEAN DEFAULT FALSE
retraction_doi            TEXT
update_type               ENUM           -- retraction | correction | addendum
                                         -- | expression_of_concern | withdrawal
last_crossref_check_at    TIMESTAMPTZ

-- ethics lifecycle
author_contacted_at       TIMESTAMPTZ
author_response           ENUM           -- approved | objected | no_response | collaborating
author_objection_action   TEXT
embargo_until             DATE

ingest_code_git_sha       TEXT NOT NULL
schema_version            TEXT NOT NULL
```

**`observation` table — the science columns you also need (not asked for, but the licence schema is useless without them):**

```
obs_id, source_id FK, site_id, network_id,
lat_public, lon_public, coord_uncertainty_m, coord_generalization,  -- see §E
datetime_utc, tz, temporal_resolution_s, aggregation,
depth_top_cm, depth_bottom_cm,
vwc_m3m3, vwc_uncertainty, qc_flag, original_units, unit_conversion,
sensor_type,        -- TDR | FDR_capacitance | CS616 | CS655 | TEROS12 | 5TM
                    -- | Watermark_matric | neutron_probe | gravimetric | CRNS
                    -- | model | satellite_retrieval | digitized_figure
sensor_make_model, calibration,   -- factory | soil_specific | unknown
salinity_corrected_bool, bulk_ec_dS_m,    -- the user's stated core concern
irrigated_bool, irrigation_method, irrigation_evidence,
sand_pct, silt_pct, clay_pct, texture_class, texture_source,
bulk_density_g_cm3, om_pct
```

**Enforcement:** adopt the **REUSE Specification 3.x** (`https://reuse.software/`) — `LICENSES/` directory with verbatim texts, SPDX headers, `reuse lint` in CI. Then add a **CI gate that fails the build if any row exported to the open-core Parquet has `redistributable_bool = FALSE` or `redistribution_tier > 'T1_attribution'`.** A licence policy that isn't a failing test is a licence policy that will be violated.

### D.4 Tiered release architecture

- **T0/T1 — open core, CC-BY-4.0, one DOI.** USDA-ARS + LTAR, SCAN/AWDB, SSURGO/gNATSGO, NASA (SMAP L3/L4, NLDAS-2, GLDAS, MODIS), ERA5-Land, ESA CCI SM, AmeriFlux, FLUXNET2015 Tier 1, COSMOS-UK, TERN/CosmOz, PANGAEA CC-BY, Dryad CC0, Zenodo/figshare CC-BY, ESSD datasets, CDL/LANID/IrrMapper — **and all figure-digitized numeric values** (facts, `LicenseRef-Facts-Feist`, with mandatory `source_doi` attribution).
- **T2 — separate physical dataset, separate DOI, CC-BY-NC-4.0.** A third for ODbL if you cannot avoid it. **Never merged into the core file, never in the same Parquet dataset.**
- **T3 — pointer-only, ships code not data.** ISMN, Oklahoma & Nebraska Mesonet, CNERN, ESDAC, restricted TPDC records, FLUXNET Tier 2. You publish: station IDs, timestamps, the exact query, the harmonisation/QC code, and `fetch_restricted.py` that reconstitutes the rows into the user's local copy after *they* authenticate under *their own* agreement. This is the standard pattern and reviewers accept it.
- **Auto-generated attribution manifest** at build time from the `source` table: `ATTRIBUTION.md`, `attribution.json`, `CITATION.cff`, `CREDITS.bib`. Every published row carries `source_id` so the manifest is verifiable by a third party.

---

## E. ETHICS AND NORMS

### E.1 Digitizing a living colleague's figures

Legally free; socially load-bearing. You built a decade of standing in a small community — protect it, and exploit the fact that the ethical move is also the *scientifically superior* one:

1. At extraction time, capture the corresponding author's email from the article metadata.
2. **Before first release**, send a standard notification: *"We digitized Figure N of [paper] for an open soil-moisture database. Here are the extracted values — please check them. We will cite you. **If you still have the original data, sending it would be more accurate than our digitization, and we'd credit you accordingly.**"*
   **This is a data-acquisition strategy disguised as an ethics protocol.** A meaningful fraction will send you the raw data, which is strictly better than digitized data, and it converts a legal-risk source into a T0/T1 source with explicit permission.
3. **Co-authorship** on the data paper for anyone contributing raw data; **acknowledgment** for everyone else.
4. **Public opt-out**: an author may request their digitized rows be moved to T3 or removed; honour within 30 days, with a versioned DOI and a changelog. Costs nothing; buys everything.

### E.2 Scooping and objections

- Notify **before** publishing, and offer an **embargo** (`embargo_until`) — "that figure is from a paper still in review, hold 12 months" is a reasonable request you should grant.
- Objection triage: **(a) accuracy** → fix or remove, always, no argument. **(b) "don't redistribute my data"** → you are legally entitled to the facts, but honour it anyway unless it guts coverage, in which case negotiate co-authorship. **(c) asserted database right or contract** → stop, escalate, **[COUNSEL]**.
- Publish the objection policy up front so it looks principled rather than reactive.

### E.3 Retraction and correction propagation

A database that silently carries retracted data is a scientific-integrity failure and will be the first thing a reviewer hunts for. Route `[recalled]`:

- **Crossref REST**: `https://api.crossref.org/works/{doi}` → read **`updated-by`** on the retracted item and **`update-to`** (with `update-type: retraction | correction | addendum | expression_of_concern | withdrawal`) on the notice record. This is the Crossmark data.
- **Retraction Watch Database**: acquired by Crossref in **Sept 2023** and released **open, CC0**. Daily CSV via Crossref Labs — `https://api.labs.crossref.org/data/retractionwatch?your@email.address` `[recalled — verify the exact URL form; the email-in-query-string convention is unusual but I believe correct]`. Also mirrored in Crossref's public data file.
- **Crossref Public Data File** (annual, CC0, torrent/S3) for a full offline check.
- **PubMed**: `PublicationType = "Retracted Publication"`.
- **Implement**: a nightly job over every `source_doi`; set `retracted_bool`, `retraction_doi`, `update_type`, `last_crossref_check_at`; exclude from the next release with an explicit changelog entry; and publish a persistent `RETRACTIONS.md`. **Version the dataset (Zenodo concept DOI + version DOIs) so removals are auditable rather than silent.**

### E.4 CARE principles and Indigenous data sovereignty

- **CARE Principles for Indigenous Data Governance** (Collective Benefit, Authority to Control, Responsibility, Ethics) — `https://www.gida-global.org/care`. Pair with FAIR; funders increasingly ask.
- Add `site_land_tenure ENUM (private_farm | tribal | public | research_station | unknown)`.
- For tribal-land sites — in the US e.g. Navajo Nation, Gila River Indian Community irrigation, Wind River, Yakama, and the 1994 land-grant tribal colleges — **do not publish coordinates or site identity without the Nation's research review board approval.** Most Nations have one (e.g. the Navajo Nation Human Research Review Board). Apply **Local Contexts TK/BC Labels** (`https://localcontexts.org/`) if requested.
- **Your IRB will almost certainly return "not human subjects research," which gives false comfort — it does not screen for any of this.** Build the screen yourself.

### E.5 Farmer data sovereignty and the coordinate-precision problem

Norm instruments to cite: the **Privacy and Security Principles for Farm Data** (American Farm Bureau Federation coalition, 2014) and the **EU Code of Conduct on Agricultural Data Sharing by Contractual Agreement** (COPA-COGECA et al., 2018) `[recalled]`.

**The risk, stated plainly:** publishing exact lat/lon of a private irrigated field lets anyone cross-reference county parcel GIS (public in most US states) to identify the operator, then combine your soil-moisture series with **OpenET** to reconstruct that operator's consumptive water use. In the western US that is legally and politically explosive — water-rights curtailment, Colorado River allocation, Ogallala depletion, Republican River compact litigation, Kansas LEMAs. A producer who let a grad student install probes in 2014 did not consent to that.

**Recommended policy — three coordinate tiers:**

| Tier | When | Published geometry |
|---|---|---|
| **Exact** | Source already published exact coords **AND** (public research station **OR** documented operator consent) | `lat`, `lon`, `coordinateUncertaintyInMeters = <site value>` |
| **Fuzzed** | Private farm, default | One-time random offset, uniform within 1–5 km; **store the offset, never re-randomise** (re-randomising lets an attacker average it away); seed kept private; `coordinateUncertaintyInMeters = 5000`, `dataGeneralizations = 'offset applied'` |
| **Generalized** | Sensitive / tribal / operator objection | ADM2 centroid or **H3 resolution-6 cell** (~3.2 km edge); `informationWithheld = 'coordinates generalized'` |

**The design trick that makes this free:** store `geom_exact` in an access-controlled column and **extract all covariates (SSURGO texture, SoilGrids, ERA5-Land, SMAP, CDL/LANID irrigation status) at the EXACT location inside your controlled build environment**, then publish the extracted covariate *values* alongside the *fuzzed* coordinate. **Model skill is preserved; location is not disclosed.** Naive fuzzing before covariate extraction destroys the soil-texture signal — the exact variable your project is built on. Get this ordering right or the whole dataset is degraded.

**Precedents to cite:**
- **GBIF sensitive-occurrence generalization** — the best transferable technical precedent. Adopt its Darwin Core fields verbatim: `decimalLatitude`, `decimalLongitude`, `coordinateUncertaintyInMeters`, `informationWithheld`, `dataGeneralizations`. See also the GBIF/IUCN *Current Best Practices for Generalizing Sensitive Species Occurrence Data*.
- **USDA NASS disclosure avoidance** — suppression of cells with fewer than 3 operations; the closest domestic agricultural precedent.
- **AmeriFlux and ISMN both publish exact station coordinates** — because their sites are overwhelmingly institutional, not private farms. **Do not read their practice as precedent for your private-field sites.** That difference is the whole point.

**[COUNSEL] — hard legal bar, not a norm:** **7 U.S.C. § 2276** and **§ 1619 of the 2008 Farm Bill** protect producer-identifying agricultural data collected by USDA (including NRCS/FSA cooperator data) from disclosure. **If any of your data originated through an NRCS/FSA cooperator agreement or an EQIP/CSP-funded installation, § 1619 may prohibit publication outright.** Screen for this explicitly; it is the one item in this document that carries statutory rather than contractual consequences.

---

## F. DELIVERABLE

### F.1 Decision table — action × jurisdiction

**P = permitted · C = conditional · X = prohibited**

| # | Action | US (§107 + contract) | EU Art. 3 (research org) | EU Art. 4 (general) | UK s.29A | JP 30-4 | SG s.244 | Contract/licence overlay |
|---|---|---|---|---|---|---|---|---|
| 1 | Bulk-download subscribed full text **via publisher API + institutional token** | **C** — §107 defensible; licence governs | **P** | **C** (opt-out) | **C** (non-comm only) | **P** | **P** | **Decisive. Get it in writing.** |
| 2 | Bulk-download subscribed full text **by scraping the website** | **C/X** — licence breach; CFAA narrowed but ToS breach is a contract breach | **C** — Art. 3(3) security measures justify API-only | **C** | **C** | **C** | **C** | **X — do not do this** |
| 3 | Bulk-download OA (PMC, Europe PMC, CORE, Copernicus, MDPI-via-PMC) | **P** | **P** | **P** | **P** | **P** | **P** | P (CC-BY) |
| 4 | Download from Sci-Hub / LibGen / Anna's Archive | **X** (*Bartz*: $3,000/work) | **X** (no lawful access) | **X** | **X** | **X** (ACA proviso) | **X** | **X** |
| 5 | Retain the corpus indefinitely on institutional servers | **C** (HathiTrust; licence governs) | **P** — Art. 3(2) express retention right | **X** — only as long as necessary | **C** (non-comm) | **C** | **C** | Licence governs |
| 6 | Share the corpus with a collaborator at another institution | **C** | **C** — Recital 15, persons involved in the research | **X** | **X** — s.29A(2) bars transfer | **C** | **C** — collaborative CDA only | Usually X |
| 7 | **Redistribute the corpus publicly** | **X** | **X** | **X** | **X** | **X** | **X** | **X** |
| 8 | Digitize numeric values from figures in subscribed articles | **P** (intermediate copying; Feist) | **P** | **C** | **C** | **P** | **P** | C |
| 9 | **Publish digitized numbers + citation + provenance** | **P** (Feist) | **P** (BHB) | **P** | **P** | **P** | **P** | C — check for a DUA on the underlying data |
| 10 | Publish figure **bitmaps** from subscription articles | **C** — few, small, in a paper (fair use + STM ≤3 figures); **X** in bulk | **C** quotation only; **X** bulk | **X** | **C**/**X** | **C** | **C** | **X in bulk** |
| 11 | Publish figure bitmaps from **CC-BY** articles | **P** w/ attribution | **P** | **P** | **P** | **P** | **P** | P |
| 12 | Train a chart-derendering model on subscription figure crops | **C** — favourable post-*Bartz*, unsettled | **P** | **C** | **C** | **P** | **P** | C — **prefer synthetic + CC-BY** |
| 13 | **Release soil-moisture ML weights** (trained on numbers) | **P** | **P** | **P** | **C** — non-commercial constraint | **P** | **P** | P |
| 14 | Commercial use / spin-out on the same corpus | **C** | **X** — Art. 3 is research-only; Art. 4 applies | **C** (opt-out) | **X** — s.29A is non-commercial | **P** | **P** | Re-negotiate everything |
| 15 | **Redistribute ISMN values** | **X** | **X** | **X** | **X** | **X** | **X** | **X — contract, not copyright** |
| 16 | Redistribute ERA5-Land / AmeriFlux / SCAN / NASA / SSURGO extracts | **P** | **P** | **P** | **P** | **P** | **P** | **P w/ attribution** |
| 17 | Publish exact coordinates of private irrigated farms | **C** — see §E.5; **X** if USDA §1619 applies | C | C | C | C | C | Ethics + §1619 **[COUNSEL]** |

**Read across row 1 and row 15 together: the binding constraints on this project are almost entirely *contractual*, not copyright. Copyright law is more permissive than your library licence and the ISMN data policy. Budget your effort accordingly.**

### F.2 Pre-flight checklist — before the first bulk download

**Do not send request #1 until every box is ticked.**

☐ **Library.** Meeting held with the scholarly communications / licensing librarian. Written confirmation of which of Elsevier / Wiley / Springer / T&F / Sage agreements permit TDM and on what terms (these agreements are confidential — **you cannot find this by searching**).
☐ **Written TDM permission** obtained or formally requested per publisher, with scope, volume, rate, purpose, and the disposition of outputs stated. **Ask Elsevier specifically whether the CC-BY-NC-on-outputs clause still applies** — if it does, it contaminates your release.
☐ **Institutional tokens** issued: Elsevier `X-ELS-Insttoken`, Wiley `Wiley-TDM-Client-Token`, Springer TDM key.
☐ **Per-publisher rate budget** written down and hard-coded: ≤1 req/s, nightly cap ≤25% of stated quota, exponential backoff on 429/503, **hard stop on first 403**, circuit breaker after N consecutive errors.
☐ **User-Agent policy** implemented, with a real live project page at the URL it cites and a monitored contact address.
☐ **Dedicated static IP / VM**, registered with library IT, **isolated from the campus subscription IP range**. Named human owner. Documented kill switch.
☐ **Domain allowlist** in the crawler — pirate mirrors architecturally unreachable, not merely prohibited.
☐ **robots.txt + `/.well-known/tdmrep.json` + ToS** fetched, parsed, hashed, stored per domain; Art. 4 reservations honoured.
☐ **Request log** schema live (URL, DOI, ts, status, bytes, UA, robots decision) — your good-faith evidence.
☐ **Licence schema + REUSE + the CI gate** implemented **before** ingest, not after. Retrofitting per-row provenance onto 10⁶ rows is the failure mode that kills these projects.
☐ **Legal sign-off** from the Office of General Counsel / research compliance on the written TDM plan.
☐ **Export control / research security** review if any Chinese (TPDC, CNERN), Russian or sanctioned-jurisdiction source or partner is involved. (Fundamental-research exclusion, 15 CFR 734.8, probably applies — get it blessed anyway.) **[COUNSEL]**
☐ **USDA § 1619 screen** for any NRCS/FSA-cooperator-derived site. **[COUNSEL]**
☐ **Data Management Plan** written (NSF/USDA-NIFA format), naming the repository, licence tiers, embargo policy, coordinate-generalization policy, retraction-propagation job, and the author-objection procedure. The **2022 OSTP "Nelson memo"** public-access policy (all federally funded data openly available from 31 Dec 2025) **helps you** — cite it when requesting data from other federally funded PIs.
☐ **Author-notification template** drafted and the opt-out policy published.
☐ **Liability disclaimer** drafted: no warranty; **not for operational irrigation-scheduling decisions**; model card states the irrigated-field domain and the clay/salinity sensor limitations.
☐ **Code licence decided**: Apache-2.0 for your code; **`pdfplumber` (MIT) / `pypdfium2` (BSD-3) instead of `PyMuPDF` (AGPL-3.0)**; check WebPlotDigitizer's current licence before embedding it.

### F.3 Public release plan

| Tier | Contents | Licence | Repository | Embargo |
|---|---|---|---|---|
| **Code** | Harvest, digitization, harmonisation, QC, ML pipeline, `fetch_restricted.py` | **Apache-2.0** | GitHub + Zenodo release DOI | none |
| **T0/T1 open core** | PD + CC-BY + digitized numbers | **CC-BY-4.0** + auto-generated attribution manifest | **Zenodo** (concept DOI + versioned DOIs) as the archival copy; **Hugging Face Datasets** mirror for ML discoverability; S3 requester-pays for the full Parquet if >50 GB | Release at data-paper submission |
| **T2 restricted-open** | CC-BY-NC rows (separate) and ODbL rows (separate again) | **CC-BY-NC-4.0** / **ODbL-1.0**, distinct DOIs, never merged | Zenodo | Same |
| **T3 pointer-only** | Station IDs, timestamps, queries, harmonisation code — **no values** | Apache-2.0 (code) | GitHub | none |
| **Model weights** | Soil-moisture regressor + (synthetic-trained) chart derenderer | **Apache-2.0** or **CC-BY-4.0**, with a model card | Hugging Face + Zenodo | Release with the methods paper |
| **Data paper** | **ESSD (Copernicus, CC-BY-4.0)** — the natural venue; a *Scientific Data* or *Vadose Zone Journal* alternative | CC-BY-4.0 | — | — |

**Format:** Parquet partitioned by `year` / `network`, plus a small CSV demo subset; Frictionless Data / Croissant metadata for ML discoverability; `CITATION.cff`; per-row `source_id` so every value is traceable to its licence.

### F.4 What needs university counsel, not a web search

1. **Whether the library's Elsevier/Wiley/Springer/T&F/Sage agreements permit TDM** — confidential contracts; only the librarian and counsel can read them. **The single most important unknown in this document.**
2. **Whether a US university can rely on EU Art. 3** for copies made on EU cloud infrastructure — territoriality and choice of law, genuinely unsettled.
3. **Whether the sui generis database right attaches to any specific source, and whether your extraction is substantial** — needs an EU-qualified lawyer if you have an EU partner.
4. **USDA § 1619 / 7 U.S.C. § 2276** exposure for any NRCS/FSA-cooperator-derived site — statutory, not contractual.
5. **State water-rights confidentiality and open-records** implications of publishing farm-level water-use-adjacent data, particularly in CO, KS, NE, AZ, CA.
6. **Export control / NSPM-33 research security** for Chinese data-source collaborations.
7. **Liability and indemnity** for an openly released model that could inform irrigation decisions.
8. **Whether any Elsevier "outputs must be CC-BY-NC" clause survives** and what it does to your release licence.
9. **Institutional risk tolerance** for the digitization programme as a whole — this is a decision, not a research finding, and it should be made by a named administrator in writing before you start.

---

## THREE THINGS THAT CHANGE THE PROJECT'S SHAPE

1. **Invert the pipeline.** Mine **ESSD data papers, DataCite `rightsList`, Zenodo/Dryad/PANGAEA, USDA-ARS/LTAR, SCAN/AWDB, NASA and Copernicus first.** Those are open, machine-readable, higher-fidelity, and carry no legal risk. Digitize figures only for the gaps that remain. You will likely find that the open sources supply the great majority of usable irrigated multi-depth soil moisture, and that digitization is a *supplement*, not the foundation. That single reordering removes most of §A and §B from the critical path.
2. **The author-notification email is a data-acquisition tool.** Every author who replies with raw data converts a T-risky digitized row into a clean, higher-accuracy, explicitly-permitted one — and recruits a collaborator in a field where you already have standing.
3. **Extract covariates at exact coordinates, publish fuzzed coordinates.** Get the ordering wrong and you either disclose farmers' locations or destroy the soil-texture signal your entire hypothesis rests on.

---

**Sources** — `[ALL RECALLED FROM TRAINING; SEARCH BUDGET WAS EXHAUSTED BEFORE ANY QUERY RAN. VERIFY EVERY URL BEFORE USE.]`

[EUR-Lex Directive (EU) 2019/790](https://eur-lex.europa.eu/eli/dir/2019/790/oj) · [Directive 96/9/EC](https://eur-lex.europa.eu/eli/dir/1996/9/oj) · [CDPA s.29A](https://www.legislation.gov.uk/ukpga/1988/48/section/29A) · [W3C TDMRep](https://www.w3.org/community/tdmrep/) · [Elsevier TDM](https://www.elsevier.com/about/policies-and-standards/text-and-data-mining) · [dev.elsevier.com](https://dev.elsevier.com/) · [Elsevier API quotas](https://dev.elsevier.com/api_key_settings.html) · [Wiley TDM](https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining) · [Springer Nature TDM](https://www.springernature.com/gp/researchers/text-and-data-mining) · [dev.springernature.com](https://dev.springernature.com/) · [Taylor & Francis TDM](https://taylorandfrancis.com/partnership/commercial/text-and-data-mining/) · [Crossref REST API](https://api.crossref.org/) · [Retraction Watch via Crossref Labs](https://api.labs.crossref.org/data/retractionwatch) · [PMC OA Service](https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/) · [PMC FTP](https://ftp.ncbi.nlm.nih.gov/pub/pmc/) · [Europe PMC REST](https://www.ebi.ac.uk/europepmc/webservices/rest/) · [OpenAlex API](https://api.openalex.org/) · [Unpaywall API](https://unpaywall.org/products/api) · [CORE API v3](https://api.core.ac.uk/v3/) · [DataCite API](https://api.datacite.org/) · [STM Permissions Guidelines](https://www.stm-assoc.org/intellectual-property/permissions/permissions-guidelines/) · [ISMN](https://ismn.earth/en/data/data-policy/) · [AmeriFlux Data Policy](https://ameriflux.lbl.gov/data/data-policy/) · [FLUXNET2015 policy](https://fluxnet.org/data/fluxnet2015-dataset/data-policy/) · [Ag Data Commons](https://agdatacommons.nal.usda.gov/) · [USDA LTAR](https://ltar.ars.usda.gov/) · [NRCS AWDB REST](https://wcc.sc.egov.usda.gov/awdbRestApi/) · [Soil Data Access](https://sdmdataaccess.sc.egov.usda.gov/) · [Oklahoma Mesonet](https://www.mesonet.org/) · [Nebraska Mesonet](https://mesonet.unl.edu/) · [UKCEH EIDC](https://catalogue.ceh.ac.uk/) · [Open Government Licence v3](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) · [TERENO/TEODOOR](https://teodoor.icg.kfa-juelich.de/) · [TERN](https://www.tern.org.au/) · [CosmOz](https://cosmoz.csiro.au/) · [TPDC](https://data.tpdc.ac.cn/) · [CNERN](http://www.cnern.org.cn/) · [Copernicus CDS](https://cds.climate.copernicus.eu/) · [ESA CCI Soil Moisture](https://climate.esa.int/en/projects/soil-moisture/) · [NASA CMR](https://cmr.earthdata.nasa.gov/search/) · [Zenodo API](https://zenodo.org/api/) · [Dryad API](https://datadryad.org/api/v2/) · [figshare API](https://api.figshare.com/v2/) · [PANGAEA](https://www.pangaea.de/) · [OpenET terms](https://openetdata.org/terms-of-use/) · [Google Earth Engine Terms](https://earthengine.google.com/terms/) · [SoilGrids REST](https://rest.isric.org/soilgrids/v2.0/) · [ISRIC maps](https://maps.isric.org/) · [CropScape/CDL](https://nassgeodata.gmu.edu/CropScape/) · [GIDA CARE Principles](https://www.gida-global.org/care) · [Local Contexts](https://localcontexts.org/) · [REUSE Specification](https://reuse.software/) · [SPDX License List](https://spdx.org/licenses/)