<!--
Compiled from a research sweep, not written by hand. Preserved verbatim because
it is reference material the implementation draws on rather than prose meant to
be read start to finish.

CONFIDENCE: the sweep's web-search budget was exhausted before these sections
ran, so everything in them is recalled from model knowledge and NONE of it was
corroborated by a search. Every URL and every accuracy figure must be verified
before it is relied on. Nothing here is legal advice.
-->

# Non-Anglophone & Grey-Literature Harvest Design for Irrigated Multi-Depth Soil Moisture

## ⚠️ CRITICAL CAVEAT ON CONFIDENCE — READ FIRST

**The session's WebSearch budget (200/200 calls) was already exhausted before this subtask issued its first query. Zero searches executed. Every fact below is `recalled` from training, none is `confirmed`.** I have marked per-item confidence as **[H]** (high — I'd bet on it), **[M]** (medium — probably right, verify), **[L]** (low — treat as a hypothesis to test). Any URL marked [L] should be probed before you write code against it. I have deliberately written "unknown" rather than invent endpoints in several places.

Verification is cheap: `curl -sI <url>` and `curl -s '<oai_base>?verb=Identify'` will settle 90% of these in ten minutes.

---

## 0. THE SINGLE MOST IMPORTANT REFRAME

Before the source list: **your sweep is optimizing the wrong extraction target.**

Digitizing a figure gives you ~5–15 points per curve with 2–5% positional error, after expensive per-figure human calibration. A thesis appendix or an experiment-station report **table** gives you 50–500 exact values with unit labels, depth increments, dates and replicate structure, extractable with a table-structure model at ~100× the throughput and ~0 error.

Irrigation MSc/PhD theses are the densest table source on Earth for this variable, because degree requirements force authors to publish raw data in appendices that journals strip out. Experiment-station and AICRP annual reports are second. **Rank the whole harvest by "probability the document contains a depth × date soil-water table", not by "is it a journal article".** That single change reorders everything below and is why §3 outranks §1.

---

## 1. NON-ENGLISH BIBLIOGRAPHIC DATABASES

### 1.1 China — the largest pool and the hardest access

| Source | Base URL | API? | Access reality |
|---|---|---|---|
| CNKI | `https://www.cnki.net` (overseas: `https://oversea.cnki.net`, `https://chn.oversea.cnki.net`) | **No public API** [H] | Institutional subscription, per-module. Export capped (~500 records/export, typically 50/page). Overseas access to several CNKI databases was restricted/withdrawn 2022–2023 following the SAMR antitrust action and data-security review; current overseas availability is module-dependent and unstable. **[M]** |
| CNKI Scholar | `https://scholar.cnki.net` | No [H] | Discovery layer over CNKI + foreign content. No bulk. |
| Wanfang Data | `https://www.wanfangdata.com.cn`, EN: `https://g.wanfangdata.com.cn` | No public API [H] | Subscription. Has a thesis database (中国学位论文全文数据库) — very high-value, ~6M theses **[M]** |
| VIP / Cqvip | `https://www.cqvip.com` | No [H] | Subscription; weakest of the three for full text |
| CSCD | Delivered *inside Web of Science* as a separate index [H] | **Not exposed via the WoS API** [M] — WoS Starter/Expanded APIs cover Core Collection; CSCD requires UI access **[M]** | ~1,300 journals |

**Honest assessment for a US-based researcher: do not attempt programmatic CNKI/Wanfang/VIP harvesting.** No API exists, the ToS forbid bulk retrieval, overseas IP access is unreliable, and CAJ-format full texts need CAJViewer. This is a collaborator problem, not an engineering problem.

**The route that actually works — bypass CNKI entirely via publisher-side journal sites.** Most Chinese society journals self-host on the **Magtech (北京玛格泰克) / Tsinghua Tongfang OJS-like platforms**, serve free PDFs, and have highly predictable URL patterns (`/CN/Y2019/V35/I12/1` volume-issue browse, `/EN/abstract/abstract12345.shtml`). Several expose OAI. **[M]** These are scrapable at low political and legal risk and carry bilingual abstracts.

Highest-yield venues (all carry irrigated multi-depth profiles routinely):
- **农业工程学报** *Transactions of the CSAE* — `https://www.tcsae.org` **[H]** — free PDFs, bilingual abstracts. The single best Chinese venue for this topic.
- **灌溉排水学报** *Journal of Irrigation and Drainage* — `http://www.jid.net.cn` **[M]** (IWHR / Chinese National Committee on Irrigation and Drainage)
- **中国生态农业学报** *Chinese Journal of Eco-Agriculture* — `http://www.ecoagri.ac.cn` **[M]**
- **干旱地区农业研究** *Agricultural Research in the Arid Areas* — journal site exists; exact domain **[L]**, find via the Northwest A&F University press
- Also: **节水灌溉** *Water Saving Irrigation*; **水土保持学报** *J. Soil and Water Conservation*; **农业机械学报** *Trans. CSAM*; **水利学报** *J. Hydraulic Engineering*; **应用生态学报**; **中国农业科学** *Scientia Agricultura Sinica*
- Special note: **膜下滴灌** (mulched drip irrigation) in Xinjiang cotton is an enormous, almost entirely Chinese-language literature with dense 0–100 cm profile data. It is probably the largest single coherent block of irrigated multi-depth soil moisture measurements in the world and is invisible to OpenAlex.

**Chinese data hosts (much better value than the literature):**
- **Science Data Bank** — `https://www.scidb.cn` (EN `/en`), CAS-operated, DataCite DOIs. **Harvest trick: enumerate it through the DataCite REST API** (`https://api.datacite.org/dois?query=...&client-id=...`) rather than scidb.cn itself — free, documented, no Chinese account. **[M]**
- **National Tibetan Plateau Data Center (TPDC)** — `https://data.tpdc.ac.cn` (EN `/en`). **[H]** Hosts **HiWATER / Heihe River Basin** datasets: wireless soil-moisture networks (SoilNET/WATERNET, ~50 nodes) in the **Yingke and Daman irrigation districts** (Zhangye oasis, irrigated maize), at 4/10/20/40/80/120 cm, multi-year. Free after registration. **This is the highest-value single Chinese resource on this entire page and it requires no Chinese-language reading.**

### 1.2 Iran — high density, awkward access, but an OJS backdoor

- **SID.ir** — `https://www.sid.ir` (English UI available). Free full-text PDFs for a large share of Iranian journals. No API; scrapable with care. **[M]**
- **Magiran** — `https://www.magiran.com` — abstracts free, full text largely paywalled. **[M]**
- **Noormags** — `https://www.noormags.ir` — subscription. **[M]**
- **IranDoc "Ganj"** (national thesis registry) — `https://ganj.irandoc.ac.ir` **[M]**. Metadata browsable; **full text generally requires an Iranian national ID login** — effectively closed to a foreign researcher. **[M]**
- **ISC** (Islamic World Science Citation Center) — `https://mjl.isc.ac` / `isc.ac` — regional index for Iran + OIC. **[M]**

**The backdoor that makes Iran tractable:** virtually every Iranian university journal runs **OJS 3** or the Persian **Sinaweb/Yektaweb JMS** platform, both of which expose **OAI-PMH at `<journal_base>/oai`**. **[M–H on the pattern, per-journal verification needed]** Target:
- `https://jsw.um.ac.ir` — *Journal of Water and Soil* (نشریه آب و خاک), Ferdowsi Univ. Mashhad
- `https://ijswr.ut.ac.ir` — *Iranian Journal of Soil and Water Research*, Univ. of Tehran
- `https://jise.scu.ac.ir` — *Irrigation Sciences and Engineering* (JISE), Shahid Chamran Univ.
- *Iranian Journal of Irrigation and Drainage* (مجله آبیاری و زهکشی ایران) — IAID; domain **[L]**
- *Water Research in Agriculture* (Soil and Water Research Institute, SWRI)

Try `?verb=Identify` then `?verb=ListRecords&metadataPrefix=oai_dc` on each. Most Iranian journal OAI feeds carry **bilingual Persian/English** `dc:title` and `dc:description` — you can triage in English and only OCR the Persian PDF when it scores.

**Legal/practical:** scholarly information exchange falls under the OFAC "informational materials" exemption, but **do not pay Iranian entities for subscriptions** without counsel. Some `.ir` domains are intermittently unreachable from US IPs. Stick to the free OA journals.

### 1.3 Turkey

- **DergiPark** — `https://dergipark.org.tr` — ~2,000+ Turkish journals on customized OJS, overwhelmingly free full text. Per-journal OAI is the likely route: try `https://dergipark.org.tr/api/public/oai/` **[L]** and `https://dergipark.org.tr/tr/pub/<journal>/oai` **[L]**. There is a public journal-list JSON under `/api/public/journals` **[L]**. **Verify all three.** DergiPark *is* harvested by BASE and OpenAIRE, so you get partial coverage free — but article-level Turkish abstracts and PDFs are better from the source.
- **TR Dizin (ULAKBİM/TÜBİTAK)** — `https://search.trdizin.gov.tr`. The SPA is backed by a JSON endpoint of the form `https://search.trdizin.gov.tr/api/defaultSearch/publication?q=...` **[L — sniff the network tab to confirm]**. Turkish national journal index with TR+EN abstracts.
- **YÖK Ulusal Tez Merkezi** — `https://tez.yok.gov.tr` **[H]**. National thesis center, **600k–800k theses**, a large and growing share full-text open PDF. **[M]** No API; search is a session-token POST form with bot defenses. Scrapable with effort and patience. **High yield**: Turkish Ziraat Fakültesi MSc theses on *damla sulama* (drip) in cotton/maize report 0–30/30–60/60–90/90–120 cm water contents in appendix tables as a matter of course.
- Venues: *Toprak Su Dergisi*; *Tarım Bilimleri Dergisi* (Ankara Univ.); **Harran Tarım ve Gıda Bilimleri Dergisi** (Şanlıurfa — the GAP irrigation scheme, extremely on-target); Süleyman Demirel, Çukurova and Ege Ziraat Fakültesi Dergileri.

### 1.4 Latin America — the best-engineered non-English stack

- **SciELO** — network OAI `http://www.scielo.org/oai/scielo-oai.php`; per-collection e.g. `https://www.scielo.br/oai/scielo-oai.php`, plus `.org.mx`, `.cl`, `.org.co`, `.org.ar`, `.org.pe`, `.sld.cu`, `.edu.uy`, `.org.bo`, `.org.ve`. **[M–H]**
  **Better: the ArticleMeta API** — `http://articlemeta.scielo.org/api/v1/` with `/article/`, `/journal/`, `/collection/` endpoints, returning full JSON records. **Python clients: `articlemetaapi` and `xylose` (both on PyPI, SciELO-maintained).** **[M]** SciELO also publishes full-text JATS XML in bulk. This is the cleanest non-English harvest on the list.
- **Redalyc** — `https://www.redalyc.org`, ~1,300 journals, OAI at `https://www.redalyc.org/oai.jsp` **[L]**. Overlaps SciELO substantially.
- **LA Referencia** — `https://www.lareferencia.info` — aggregates the national OA repository networks of Brazil (OASISBR), Argentina (SNRD), Chile, Colombia, Mexico, Peru, Ecuador, Uruguay, Costa Rica, El Salvador. ~4M records **[M]**, heavily weighted to **theses**. OAI at `http://www.lareferencia.info/vufind/OAI/Server` **[L]**. **One-stop shop for Ibero-American ETDs.**
- **Dialnet** — `https://dialnet.unirioja.es`, ~8M Spanish-language documents including *Dialnet Tesis*. API only for **Dialnet Plus** subscribing institutions **[M]**; scraping discouraged. Use for discovery, not bulk.
- **Embrapa** — the grey-literature jackpot:
  - **Alice** (peer-reviewed) `https://www.alice.cnptia.embrapa.br` → OAI `.../oai/request` **[M]**
  - **Infoteca-e** (technical series) `https://www.infoteca.cnptia.embrapa.br` → OAI `.../oai/request` **[M]**
  - **BDPA** `https://www.bdpa.cnptia.embrapa.br` (union catalogue)
  Infoteca-e holds the *Boletim de Pesquisa e Desenvolvimento*, *Circular Técnica* and *Documentos* series. **Embrapa Semiárido (Petrolina)** — irrigated mango/grape/melon in the São Francisco valley with tensiometer and TDR profiles — and **Embrapa Arroz e Feijão**, **Embrapa Milho e Sorgo**, **Embrapa Cerrados** are dense with depth-resolved irrigation data.
- Also: **INTA Argentina** `https://repositorio.inta.gob.ar` (DSpace + OAI) **[M]**; **IMTA Mexico** / *Tecnología y Ciencias del Agua*; **Colegio de Postgraduados** (*Agrociencia*, *Terra Latinoamericana*); **INIA** Chile/Uruguay/Spain.

### 1.5 Japan

- **J-STAGE Web API** — `https://api.jstage.jst.go.jp/searchapi/do?service=3&...` **[M]**. `service=2` = issue-level, `service=3` = article-level. Parameters include `pubyearfrom`, `pubyearto`, `material`, `article`, `author`, `affil`, `keyword`, `abst`, `text`, `issn`, `cdjournal`, `start`, `count`. Returns Atom XML. **Free, no API key.** **[M]**
- **CiNii Research** — `https://cir.nii.ac.jp` with OpenSearch: `https://cir.nii.ac.jp/opensearch/all?q=...&format=json` **[M]**. Covers articles + books + dissertations + datasets.
- **IRDB** (NII) — `https://irdb.nii.ac.jp` — aggregates ~1,000 Japanese institutional repositories including **博士論文** doctoral dissertations; OAI at `https://irdb.nii.ac.jp/oai` **[L]**.
- Venues: **農業農村工学会論文集** (*Trans. JSIDRE*) and **土壌の物理性** (*J. Japanese Soc. Soil Physics*), both free on J-STAGE. **[M]**
- **Honest downgrade:** Japanese irrigation research is dominated by flooded paddy, where "multi-depth soil moisture" is largely saturated/percolation work — a poor match for your unsaturated-profile target. Search **畑地灌漑** (upland-field irrigation) specifically to filter to the useful subset.

### 1.6 Korea

- **KCI** — `https://www.kci.go.kr`; **Open API** at `https://open.kci.go.kr/po/openapi/openApiSearch.kci` with a free registered key **[M]**.
- **ScienceON (KISTI)** — `https://scienceon.kisti.re.kr`, API gateway `https://scienceon.kisti.re.kr/apigateway/` **[M]**, key required. Includes KISTI-held **national R&D reports** (grey lit).
- **RISS** — `https://www.riss.kr` for theses; no API.
- Same paddy-dominance caveat as Japan. Low priority.

### 1.7 Russia / Central Asia

- **CyberLeninka** — `https://cyberleninka.ru` — ~3M **open** full-text articles. OAI at `https://cyberleninka.ru/oai` **[M]**; JSON search backend `https://cyberleninka.ru/api/search` (POST `{q, size, from}`) **[L]**. Free full text makes this far more useful than eLIBRARY.
- **eLIBRARY.RU** — `https://elibrary.ru` — ~40M items, **no public API, registration-walled, aggressive anti-bot** **[H]**. Payment to Russian entities is sanctions-complicated. **Do not attempt.**
- Venues: *Мелиорация и водное хозяйство* (Land Reclamation and Water Management), *Агрохимия*, *Почвоведение* (Eurasian Soil Science — has an English Springer edition already in OpenAlex).
- Central Asia: **SIC-ICWC** (`http://sic.icwc-aral.uz`) reports on Fergana Valley / Golodnaya Steppe cotton irrigation **[M]**; much is Russian-language PDF on a plain web server — wget-able, no API.
- Soviet-era literature uses **запасы влаги** (moisture storage, mm per layer) rather than θ — your schema must accept this.

### 1.8 India — English-language, wide open, and badly under-harvested

- **KrishiKosh** — `https://krishikosh.egranth.ac.in` **[M]** — the ICAR/e-Granth repository of **State Agricultural University theses** and legacy bulletins. DSpace; OAI probable at `/oai/request` **[L]**. **More on-target than Shodhganga for agronomy.**
- **KRISHI** (ICAR Research Data Repository) — `https://krishi.icar.gov.in` **[M]** — ICAR institute publications, annual reports, technical bulletins. DSpace-based; OAI **[L]**. Key institutes: **CSSRI Karnal** (salinity + irrigation — directly addresses your sensor-vs-salinity problem), **IIWM Bhubaneswar**, **CAZRI Jodhpur**, **IISWC**, **WTC IARI**.
- **Shodhganga** — `https://shodhganga.inflibnet.ac.in`, DSpace, OAI at `https://shodhganga.inflibnet.ac.in/oai/request` **[M–H, DSpace default]**. Size: crossed 400k full-text theses around 2022; likely **550k+ now** **[M]**. Companion **Shodhgangotri** for synopses. Full-text PDFs, English, with appendix tables. **This is the single largest untapped thesis pool for irrigation agronomy on the planet.**
- **AICRP on Irrigation Water Management (AICRP-IWM)** annual reports — coordinated multi-centre trials across ~20 Indian agro-climatic zones, decades deep, all with depth-wise soil moisture. PDFs on `iiwm.icar.gov.in` **[M]**. Extremely high density, essentially zero competition.
- Journals: *Indian Journal of Agricultural Sciences*, *Journal of Agricultural Physics*, *J. Indian Soc. Soil Science*, *Indian Journal of Agronomy* — most ICAR journals are on **OJS at `https://epubs.icar.org.in`** → per-journal `/oai` **[M]**.
- **Indian Citation Index** — commercialized, unstable, low marginal value. **Skip.**

### 1.9 Arab world

- **Egyptian Knowledge Bank** — `https://www.ekb.eg`. The harvestable part is **`https://journals.ekb.eg`**: a national **OJS multi-journal platform hosting ~800 Egyptian journals, fully open access**, with English + Arabic metadata. OJS → **per-journal OAI at `https://<journal>.journals.ekb.eg/oai`** **[M–H on the pattern]**. **[H]** that the platform exists and is OA.
  High-yield titles: *Journal of Soil Sciences and Agricultural Engineering* (Mansoura), *Misr Journal of Agricultural Engineering*, *Egyptian Journal of Soil Science*, *Annals of Agricultural Science* (Ain Shams), *Alexandria Science Exchange Journal*. Nile Delta and New Lands irrigated wheat/maize/cotton with 15/30/45/60 cm sampling is the house style. **This is the best effort-to-yield ratio in the Arabic-speaking world by a wide margin, and much of it is written in English.**
- **ASJP (Algeria)** — `https://www.asjp.cerist.dz` — national OJS-like platform, free **[M]**.
- **AGORA / Research4Life** — `https://agora.research4life.org`. **Not applicable.** It is an *access programme* for eligible low-income institutions, not an index, and a US-based researcher is ineligible. **Remove from the plan.**

---

## 2. AGRICULTURE-SPECIFIC INDEXES

### 2.1 FAO AGRIS — the highest-leverage item in this entire brief

`https://agris.fao.org` **[H]**. Search UI `https://agris.fao.org/search/en?query=...` **[M]**.

- **~12–15 million records** **[M]**, contributed by ~400–500 national data providers across ~150 countries in ~90 languages.
- **Purpose-built for exactly your gap**: it indexes national agricultural journals, conference proceedings, extension bulletins, technical reports and theses that OpenAlex/Crossref never see, because contributions come from national AGRIS centres rather than from DOI registration.
- **API status: genuinely uncertain.** The 2022 Angular rewrite is backed by a JSON search service, but I will not fabricate its path. **Action: open the search page and inspect the XHR calls.** The legacy `https://agris.fao.org/agris-search/searchIndex.do` endpoint existed pre-rewrite **[M]**. Whether a public OAI-PMH or bulk dump of the full corpus exists: **unknown — verify.** Contact `agris@fao.org`; AGRIS has historically supplied bulk AGRIS-AP XML to researchers on request. **[M]**
- **AGROVOC SPARQL endpoint — `https://agrovoc.fao.org/sparql` [M–H]** — see §5; this is your multilingual query-generation engine and is definitely worth wiring up regardless of what AGRIS's article API turns out to be.

### 2.2 CAB Abstracts / CABI Digital Library

`https://www.cabidigitallibrary.org` **[H]**. Subscription only; also delivered via Web of Science, Ovid, EBSCO.
- **CAB Abstracts: ~10–12M records from 1973** plus **CAB Abstracts Archive (1910–1972, ~2M)** **[M]**.
- Indexes ~10,000 serials **plus conference proceedings, annual reports, theses and bulletins in 50+ languages, every record with an English abstract.** This English-abstract layer over non-English primary literature is exactly what you need for triage, and it is the one thing OpenAlex structurally cannot replicate.
- **No public API.** TDM requires a negotiated CABI licence. Realistic path: get your library to check the subscription, then use the platform's export (capped) or request a TDM agreement.
- **agriRxiv** — `https://agrirxiv.org` **[M]** — CABI preprint server, low thousands of items, largely already in OpenAlex. Marginal.

### 2.3 USDA NAL

- **AGRICOLA** — `https://agricola.nal.usda.gov` **[H]**, ~5–6M records. API status **[L]**; historically Z39.50 and periodic bulk citation files. Check `https://www.nal.usda.gov/` for current data-services documentation.
- **Ag Data Commons** — `https://agdatacommons.nal.usda.gov` **[M]** — USDA-funded datasets, now on a Figshare-style platform (Figshare has a documented REST API, which would make this harvestable). **Contains USDA-ARS soil water datasets including Bushland lysimeter-area neutron-probe profiles.** **[M]**
- **NAL Thesaurus (NALT)** linked data — `https://lod.nal.usda.gov` **[M]** — English/Spanish agricultural vocabulary, useful alongside AGROVOC.

### 2.4 FAO document repository

FAO migrated to a **DSpace-based "FAO Knowledge Repository" at `https://openknowledge.fao.org`** (from the old `fao.org/documents`) around 2023 **[M]**. DSpace 7 → REST at `/server/api` and **OAI at `/oai/request`** **[M]**. Holds the **FAO Irrigation & Drainage Paper series** (24 Doorenbos & Pruitt; 33 *Yield response to water*; 56 Allen et al.; 66) and the FAO Soils Bulletins — reference material rather than raw data, but the I&D papers' worked examples contain real field profiles.

### 2.5 What these index that OpenAlex misses

Concretely: national agricultural journals without DOIs; ministry and research-institute bulletin series; conference and congress proceedings (ICID, ASABE regional, national irrigation societies); FAO/IAEA technical documents; extension circulars; and university theses from non-DOI-registering institutions. AGRIS and CAB Abstracts are the only two indexes on Earth built to catch all of these, and **AGRIS is free**.

---

## 3. GREY LITERATURE AND THESES — *highest priority tier*

### 3.1 The systematic enumeration strategy (do this first)

Do not hand-curate repositories. Do this:

1. **Pull the repository registries via API:**
   - **OpenDOAR** — `https://v2.sherpa.ac.uk/opendoar/`; REST: `https://v2.sherpa.ac.uk/cgi/retrieve?item-type=repository&api-key=<key>&format=Json` **[M]**. Free key on registration. ~6,000 repositories, each record carrying **subject classification, country, software platform and OAI base URL**.
   - **ROAR** — `https://roar.eprints.org` **[M]**, ~5,000 repositories, similar fields.
   - **OpenAIRE Graph** — `https://api.openaire.eu` plus **full dumps on Zenodo (~200M records)** **[M]**. OpenAIRE already harvests LA Referencia, IRDB, DergiPark and most national ETD networks. *The task brief did not list OpenAIRE as covered — it is the cheapest single way to acquire millions of non-English repository records and you should add it.*
2. **Filter** the registry to `subject ∈ {Agriculture, Environment, Earth Sciences}` ∪ `country ∈ {your target list}` ∪ `type = thesis repository`.
3. **Harvest** every OAI base URL with `metadataPrefix=oai_dc` and a `set` filter for theses where available.
   Python: **`oaipmh-scythe`** (maintained successor to `sickle`), or `pyoai`, or the `oai-harvest` CLI. **[M]**
4. **Score** records with a multilingual keyword model (§5) and only then fetch PDFs.

This turns "find the repositories" from a manual research problem into a ~200-line script.

### 3.2 Named aggregators

| Source | URL | Size | Harvest |
|---|---|---|---|
| **NDLTD Global ETD Search** | `https://search.ndltd.org` | ~6M ETD records **[M]** | VuFind over OAI-harvested metadata. Programmatic access **[L]** — check for a VuFind API |
| **OATD.org** | `https://oatd.org` | ~7.5M theses, 1,100+ institutions **[M]** | **No API**, restrictive robots.txt. Use for manual spot-checks only |
| **DART-Europe** | `https://www.dart-europe.org` | ~1.2M European theses, 500+ universities **[M]** | Relaunched on a new platform; OAI availability **[L]** |
| **EThOS (British Library)** | `https://ethos.bl.uk` | ~500k | **Offline since the Oct 2023 cyberattack** **[H]**. BL released the **EThOS metadata snapshot (~500k records) as CC0 on the BL Research Repository `https://bl.iro.bl.uk`** **[M]** — download it; full-text ordering is *not* restored, so resolve hits to the awarding university's own IR |
| **Theses.fr** | `https://theses.fr` | ~500k+ French theses | Has a documented API, `https://theses.fr/api/v1/...` **[M]**. High value: CIRAD/IRD/INRAE theses on Sahel, Maghreb and SE Asian irrigation, French-language, with appendix data |
| **ProQuest PQDT Global** | `https://about.proquest.com/...` | ~5.5M records, 3M+ full text **[M]** | Subscription. **Bulk text only via TDM Studio** (`https://tdmstudio.proquest.com`) — a walled Jupyter workbench, separate institutional subscription, **no raw-text export** (derived results only) **[M]**. There is a ProQuest Search API for subscribers **[L]**. Realistic: one-PDF-at-a-time is legal and fine; bulk needs TDM Studio |

### 3.3 US land-grant institutional repositories

**The platform trick:** most run **Digital Commons/bepress** (Elsevier), which universally exposes **OAI-PMH at `https://<site>/do/oai/`** **[H]** plus `/sitemap.xml`. DSpace sites expose `/oai/request` **[H]**. So the whole tier is one harvester.

| Institution | Repository | Platform / OAI | Why it's high-yield for irrigation |
|---|---|---|---|
| **Kansas State** | New Prairie Press `https://newprairiepress.org` → `/do/oai/` **[M]** | Digital Commons | **Kansas Field Research / Kansas Agricultural Experiment Station Research Reports** — decades of Tribune & Garden City (SW Research-Extension Center) limited-irrigation reports with neutron-probe profiles. Also **K-REx** `https://krex.k-state.edu` (DSpace) for theses |
| **Texas A&M** | OAKTrust `https://oaktrust.library.tamu.edu` → `/oai/request` **[M]** | DSpace | Texas High Plains / **Bushland (USDA-ARS CPRL)**-adjacent theses; neutron-probe profiles to 2.4 m are standard practice there |
| **Nebraska** | `https://digitalcommons.unl.edu` → `/do/oai/` **[M]** | Digital Commons | Biological Systems Engineering theses; **Nebraska Ag Water Management Network (NAWMN)** Watermark profiles at 1/2/3 ft; Extension Historical Materials |
| **Colorado State** | Mountain Scholar `https://mountainscholar.org` **[M]**; CSU has been migrating to `https://libraries.colostate.edu/repository` **[L]** | DSpace | Limited-irrigation maize at ARDEC/Greeley; CSU is the historical home of US irrigation engineering |
| **Arizona** | `https://repository.arizona.edu` → `/oai` **[M]** | DSpace/Hyrax | **Arizona Cotton Report**, **Forage & Grain Report** series, and the complete run of *Hydrology and Water Resources in Arizona and the Southwest* |
| **UC Davis** | eScholarship `https://escholarship.org` → `/oai` **[M]**; also a **GraphQL API at `/graphql`** **[L]** | Custom | California SDI/drip in vegetables, almonds, processing tomato |
| **Washington State** | Research Exchange `https://rex.libraries.wsu.edu` **[M]** | DSpace | Columbia Basin irrigated potato/wheat |
| **Utah State** | `https://digitalcommons.usu.edu` **[M]** | Digital Commons | Very large; hosts **Utah Water Research Laboratory** reports |
| **Iowa State** | `https://dr.lib.iastate.edu` **[M]** | DSpace | **Farm Progress Reports** series |
| **Florida** | UFDC `https://ufdc.ufl.edu`; **EDIS** `https://edis.ifas.ufl.edu` **[M]** | Custom | Florida AES bulletins; humid-region supplemental irrigation |
| Also | Oklahoma State **SHAREOK** `https://shareok.org`; **South Dakota State Open PRAIRIE** `https://openprairie.sdstate.edu`; Idaho, Montana State, NDSU, Texas Tech `https://ttu-ir.tdl.org`, Purdue e-Pubs, NMSU | mixed | — |

### 3.4 State agricultural experiment station bulletins & extension publications at scale

There is no single index. The three routes that actually work:

1. **Internet Archive full-text search** — `https://archive.org/advancedsearch.php?q=...&output=json` **[M]** and the `internetarchive` Python package **[H]**. Most AES bulletin runs were digitized from land-grant libraries and are in IA. **This is free, full-text, and immediately usable.**
2. **HathiTrust** — Bib API `https://catalog.hathitrust.org/api/volumes/brief/json/...` **[M]**; and **HTRC Extracted Features** (page-level token counts for ~18M volumes, free bulk download via rsync, Python package `htrc-feature-reader`) **[M]**. Workflow: use HTRC EF token counts to find volumes with high co-occurrence of `irrigation` + `soil moisture` + depth tokens, then pull page images for those volumes only. This is the correct way to search 100 years of bulletins without downloading 100 years of bulletins.
3. **Biodiversity Heritage Library API** — `https://www.biodiversitylibrary.org/api3?...&apikey=` **[M]** — holds a surprising share of early AES bulletins.

**Blunt assessment on extension publications specifically:** low data density. Extension fact sheets give *recommendations*, not measurements. **Do not build a pipeline for edis.ifas.ufl.edu-style fact sheets.** Instead target the *Field Day Reports / Research Center Progress Reports* genre, which is where the raw plot data lives: KSU Southwest Research-Extension Center Field Day Reports, Texas A&M AgriLife Bushland/Halfway field days, UNL West Central and South Central REC reports, UC ANR Kearney Ag Research Center reports. These are almost all inside the Digital Commons/DSpace repositories above, so §3.3's harvester already catches them — you just need a genre classifier.

**Caveat on pre-1960 bulletins:** sampling conventions differ (gravimetric "% moisture in the first foot", no bulk density reported, depths in feet). You will need bulk density to convert to volumetric, and it is often absent. Flag these records `basis=gravimetric, bd=unknown` rather than silently converting.

---

## 4. INTERNATIONAL ORGANISATION AND CGIAR OUTPUTS

### 4.1 CGSpace

`https://cgspace.cgiar.org` **[H]** — the shared DSpace for most CGIAR centres. ~120,000+ items **[M]**.
- **DSpace 7 REST**: `https://cgspace.cgiar.org/server/api/discover/search/objects?query=...` (HAL+JSON) **[M]**. The legacy DSpace 6 `/rest/items` endpoint is retired **[M]**.
- **OAI-PMH**: `https://cgspace.cgiar.org/oai/request?verb=ListRecords&metadataPrefix=oai_dc` **[M]**.
- Content is dominated by **working papers, project reports and technical briefs** — precisely the grey literature that carries raw trial data. Centres: IWMI, ILRI, Alliance Bioversity-CIAT, IITA, WorldFish, ICARDA, CIP.

### 4.2 Dataverse instances — all share one API

Every Dataverse installation exposes **Search API `GET /api/search?q=...&type=dataset`**, **native API `/api/datasets/:persistentId/?persistentId=doi:...`**, file download `/api/access/datafile/<id>`, and **OAI-PMH at `/oai`**. **[H]** **Python client: `pyDataverse`** **[H]**.

- **Harvard Dataverse** `https://dataverse.harvard.edu` — hosts CGIAR collections including **IRRI** and **CIP** **[M]**
- **CIMMYT** `https://data.cimmyt.org` **[M]**
- **ICRISAT** `http://dataverse.icrisat.org` **[M]** — **the standout**: the ICRISAT Patancheru **long-term Vertisol watershed** experiments carry neutron-probe profiles at 15 cm increments to 180 cm over multiple decades, plus the VDSA village-level datasets
- **ICARDA MEL** `https://mel.cgiar.org` with `https://data.mel.cgiar.org` as a Dataverse **[M]**; MEL has a REST API **[L]**. **ICARDA's Tel Hadya (Syria) supplemental-irrigation wheat trials** — decades of neutron-probe profiles to 180 cm, subject of an explicit ICARDA data-rescue programme. Extremely on-target for water-limited irrigated systems.
- **IWMI** — publications live on CGSpace; the **IWMI Water Data Portal** `https://waterdata.iwmi.org` **[M]** is mostly remote-sensing irrigated-area products (GIAM, GMIA), **not in-situ profiles**. Useful for stratifying your sample by irrigated extent; not a source of θ.

### 4.3 IAEA — the most under-appreciated source on this list

**`https://inis.iaea.org`** **[H]**, ~4.5M records. Non-conventional literature full texts are **free** and served from a predictable path: `https://inis.iaea.org/collection/NCLCollectionStore/_Public/<vol>/<issue>/<file>.pdf` **[M]**. A public search API: **unknown — verify**; the search UI is at `https://inis.iaea.org/search/`.

**Why this matters more than it looks:** the **Joint FAO/IAEA Division, Soil and Water Management & Crop Nutrition subprogramme (Seibersdorf)** ran Coordinated Research Projects on **neutron-probe soil water measurement in irrigated agriculture across ~40 developing countries** for three decades. The outputs are national-team datasets from Egypt, Pakistan, India, Iran, Syria, Morocco, Turkey, China, Brazil, Chile — published as TECDOCs with the profile tables intact, in English, free, and essentially never cited by the modern ML literature.

Target by series name on `https://www.iaea.org/publications` (free PDF) **[M]**:
- **TECDOC-1137**, *Comparison of soil water measurement using the neutron scattering, time domain reflectometry and capacitance methods* (2000) **[M]**
- **Training Course Series No. 30**, *Field estimation of soil water content: a practical guide to methods, instrumentation and sensor technology* (2008) **[M]** — the standard reference on your exact measurement problem
- **Technical Reports Series No. 112**, *Neutron moisture gauges* **[M]**
- TECDOC series on *Nuclear techniques in soil-plant studies for sustainable agriculture* and *Management of nutrients and water in rainfed arid and semi-arid areas* **[M]**

### 4.4 FAO AQUASTAT — be blunt

`https://data.apps.fao.org/aquastat/` **[M]**. **AQUASTAT contains no in-situ soil moisture.** It is national-scale water-resource and irrigation-area statistics (area equipped for irrigation, withdrawal by sector, irrigation technique shares). It is genuinely useful for **stratifying and weighting** your final dataset — e.g. knowing that surface irrigation is ~85% of India's irrigated area tells you whether your harvested sample is representative — but it is not a data source for the target variable. Budget one afternoon, not a pipeline.

### 4.5 ICID

`https://www.icid.org` **[H]**. World Irrigation Forum and triennial Congress proceedings, plus regional conference proceedings, published as scattered PDFs on icid.org and on ~70 national-committee websites. **No API, no consistent structure, no DOIs.** Moderate data yield, high manual effort. The journal *Irrigation and Drainage* (Wiley) is already in OpenAlex, so the marginal value is the **congress proceedings only** — worth a targeted manual sweep of the last ~8 congresses, not a crawler.

### 4.6 One source not in the brief that beats most of it

**ISMN — International Soil Moisture Network, `https://ismn.earth`** **[H]**, with the **`ismn` Python package** **[H]**. It already harmonizes 80+ networks / 3,000+ stations into one schema with **multi-depth in-situ θ, quality flags and metadata**, and it includes irrigated-cropland networks (HiWATER/Heihe, TxSON, and several national networks). Also **AmeriFlux**, **ICOS**, **FLUXNET** and **NEON** carry profile SWC at irrigated cropland sites. **Yield per unit effort here is 100–1000× anything in §1–§4**, and it should be your day-one baseline before a single PDF is parsed. The literature sweep's job is then to *extend* that baseline into the geographies and irrigation systems ISMN under-covers (China outside Heihe, Iran, Egypt, India, Turkey, Brazil) — which is exactly the gap this brief is about.

---

## 5. CROSS-LINGUAL QUERY CONSTRUCTION

### 5.1 Generate queries, don't hand-write them

Wire up **AGROVOC SPARQL** (`https://agrovoc.fao.org/sparql` **[M]**, SKOS dumps also downloadable). It carries preferred and alternate labels for agricultural concepts in **40+ languages** including zh, fa, ar, tr, es, pt, ru, ja, ko, hi. Query the concept, pull every `skos:prefLabel` and `skos:altLabel`, and you have a maintained, expert-curated multilingual synonym set for "soil water content", "irrigation", "drip irrigation", "neutron probe" etc. — better than any hand translation and updateable. Supplement with **NALT** (`https://lod.nal.usda.gov`) for EN/ES.

Below are concrete strings to seed and sanity-check against.

### 5.2 Chinese (simplified)

- **Soil moisture**: 土壤水分 · 土壤含水率 · 土壤含水量 · 土壤水分含量 · 体积含水率 · 质量含水率 · 土壤储水量 · 土壤水分动态 · 土壤水分运移
- **Irrigation**: 灌溉 · 灌水 · 灌区 · 节水灌溉 · **膜下滴灌** (mulched drip — Xinjiang cotton, huge) · 滴灌 · 地下滴灌 · 喷灌 · 微灌 · 沟灌 · 畦灌 · 漫灌 · 灌溉制度 · 灌溉定额 · 亏缺灌溉 · 调亏灌溉 · 交替隔沟灌溉
- **Profile / depth**: 土壤剖面 · 剖面 · 土层 · 不同土层深度 · 0~100 cm土层 · 垂直分布 · 土壤水分垂直变化
- **Sensors**: 中子仪 · 中子水分仪 · 中子管 · 时域反射仪 (TDR) · 频域反射 (FDR) · 土壤水分传感器 · 烘干法 (gravimetric) · 张力计 · TRIME
- **Crops**: 冬小麦 · 夏玉米 · 棉花 · 马铃薯 · 苜蓿 · 春玉米

**Simplified/traditional:** the core terms are script-invariant (土壤水分, 灌溉, 剖面 are identical in both), but **journal names and institutional affiliations are not** (农业工程学报 / 農業工程學報; 学报/學報, 农/農, 报/報, 灌溉/灌溉 ok, 干旱/乾旱). Run every query and every journal title through **OpenCC** (`pip install opencc-python-reimplemented`, configs `s2t`/`t2s`) **[H]** and index both forms. Taiwanese irrigation literature (Taiwan Agricultural Research Institute, 農業工程學報) is small but real.

**Unit trap:** Chinese papers use 质量含水率 (gravimetric, %) and 体积含水率 (volumetric, % or cm³·cm⁻³) roughly equally and do not always label which. Your extractor must detect the marker term, not just the number.

### 5.3 Persian (Farsi)

- **Soil moisture**: رطوبت خاک · محتوای آب خاک · مقدار آب خاک · رطوبت حجمی · رطوبت وزنی
- **Irrigation**: آبیاری · آبیاری قطره‌ای (drip) · آبیاری بارانی (sprinkler) · آبیاری جویچه‌ای (furrow) · آبیاری نشتی · آبیاری غرقابی (flood) · کم‌آبیاری (deficit) · آبیاری سطحی · شبکه آبیاری
- **Profile / depth**: پروفیل خاک · نیمرخ خاک (both in use) · عمق خاک · لایه‌های خاک · اعماق مختلف خاک
- **Sensors**: رطوبت‌سنج نوترونی · نوترون‌متر · TDR · انعکاس‌سنج حوزه زمانی · تانسیومتر

**Normalisation (this is where Persian recall dies):**
- **Arabic ي (U+064A) vs Persian ی (U+06CC)** and **Arabic ك (U+0643) vs Persian ک (U+06A9)** — the *same word* is stored both ways across Iranian databases. Normalise all to the Persian forms before matching.
- **ZWNJ (U+200C)** appears inside قطره‌ای, کم‌آبیاری, رطوبت‌سنج, اندازه‌گیری. Index with ZWNJ, without ZWNJ, and with a space.
- Strip tashkeel (U+064B–U+0652) and tatweel (U+0640).
- Use the **`hazm`** Python library's `Normalizer` **[M]** — it implements exactly this set.

### 5.4 Turkish

- **Soil moisture**: toprak nemi · toprak su içeriği · toprak nem içeriği · hacimsel su içeriği
- **Irrigation**: sulama · damla sulama (drip) · yağmurlama sulama (sprinkler) · karık sulama (furrow) · salma sulama (flood) · kısıtlı sulama / kısıntılı sulama (deficit) · sulama programı · sulama suyu
- **Profile / depth**: toprak profili · toprak derinliği · toprak katmanı · 0-90 cm toprak derinliği
- **Sensors**: nötron probu · nötronmetre · TDR · tansiyometre

**Normalisation:** the **dotted/dotless i** problem — Turkish `I`→`ı` and `İ`→`i`, so naive `.lower()` corrupts Turkish tokens (the classic "Turkish-I bug"). Use a locale-aware casefold. Separately, **index ASCII-folded variants** (`yagmurlama`, `kisitli`, `nem`) because Turkish authors and indexes frequently strip ğüşıöç when entering metadata.

### 5.5 Spanish

humedad del suelo · contenido de agua en el suelo · contenido hídrico del suelo · contenido volumétrico de agua · **riego** · riego por goteo · riego por aspersión · riego por surcos · riego por inundación · riego deficitario · riego deficitario controlado · lámina de riego · perfil del suelo · profundidad del suelo · capas del suelo · **sonda de neutrones** · TDR · reflectometría en el dominio del tiempo · tensiómetro

### 5.6 Portuguese

umidade do solo (BR) / **humidade do solo** (PT) · teor de água no solo · conteúdo de água no solo · **irrigação** (BR) / **rega** (PT) · irrigação por gotejamento · irrigação por aspersão · irrigação por sulcos · irrigação por inundação · irrigação deficitária · perfil do solo · profundidade do solo · camadas do solo · **sonda de nêutrons** (BR) / sonda de neutrões (PT) · TDR · tensiômetro (BR) / tensiómetro (PT)

**The BR/PT orthographic split is a real recall killer** — umidade/humidade, nêutrons/neutrões, irrigação/rega, tensiômetro/tensiómetro. Always issue both.

### 5.7 Arabic

رطوبة التربة · المحتوى المائي للتربة · محتوى الماء في التربة · **الري** · الري بالتنقيط (drip) · الري بالرش (sprinkler) · الري السطحي / الري بالخطوط (furrow/surface) · الري بالغمر (flood) · الري الناقص (deficit) · قطاع التربة · المقطع الرأسي للتربة · أعماق التربة · طبقات التربة · مسبار النيوترون · جهاز النيوترون

**Normalisation:** map أ إ آ ٱ → ا; ة → ه (index both); ى → ي; strip tashkeel and tatweel; NFKC-normalise Arabic **presentation forms (U+FB50–FDFF, U+FE70–FEFF)** to base letters — scanned-PDF text layers are full of these and they will silently fail exact matching. Handle the ال definite-article prefix (search both الري and ري). Use `camel-tools` or `pyarabic` **[M]**.

### 5.8 Japanese

土壌水分 · 土壌含水率 · 体積含水率 · **灌漑 / 潅漑 / かんがい** (all three orthographies in active use — a genuine recall trap) · **畑地灌漑** (upland-field irrigation — use this to filter out paddy) · 点滴灌漑 · 滴下灌漑 · スプリンクラー · 土層 · 深さ別 · 土壌断面 · 中性子水分計 · TDR · 時間領域反射法

### 5.9 Korean

토양수분 · 토양 수분함량 · 용적수분함량 · **관개** · 점적관수 (drip) · 스프링클러 · 밭관개 (upland irrigation) · 토양단면 · 토심 · 깊이별 · 중성자 수분계 · TDR

**Korean spacing is not standardized** (토양수분 vs 토양 수분 vs 토양의 수분). Issue spaced and unspaced variants, or use a morphological analyser (`konlpy`/`kiwipiepy`) **[M]**.

### 5.10 Russian (and Ukrainian)

влажность почвы · влагосодержание почвы · **запасы влаги в почве** (moisture storage, mm/layer — the dominant Soviet/Russian convention, reported *instead of* θ) · **орошение** · полив · капельное орошение (drip) · дождевание (sprinkler) · бороздковый полив (furrow) · затопление · дефицитное орошение · почвенный профиль · горизонты почвы · слой почвы 0-100 см · нейтронный влагомер · ТДР
Ukrainian: вологість ґрунту · зрошення · краплинне зрошення

### 5.11 Hindi — and an honest recommendation to deprioritise

मृदा नमी · मृदा जल की मात्रा · **सिंचाई** · टपक सिंचाई (drip) · फव्वारा सिंचाई (sprinkler) · मृदा परिच्छेदिका · मृदा गहराई · न्यूट्रॉन प्रोब

**Do not invest here.** Indian agricultural *research* is published in English essentially without exception; Hindi-language agronomy publishing is extension-style (*Kheti*, *Indian Farming* Hindi edition) and does not carry raw profile data. The same argument retires Bengali, Tamil, Marathi and Telugu. **Redirect that effort entirely to Shodhganga + KrishiKosh + AICRP-IWM English theses and reports**, which is where the Indian data actually is.

### 5.12 Recommended normalisation architecture

Single Unicode pipeline applied identically to queries and to indexed text:
`NFKC` → script-specific normaliser (`opencc` zh · `hazm` fa · `camel-tools` ar · locale-aware casefold tr · `kiwipiepy` ko) → **numeral transliteration** (Eastern Arabic-Indic U+0660–0669, Persian U+06F0–06F9, Devanagari U+0966–096F → ASCII; U+066B/U+066C decimal/thousands separators → `.`/`,`) → ZWNJ/ZWJ (U+200C/U+200D) variant expansion → ASCII diacritic fold as an *additional* index, never a replacement.

---

## 6. TRANSLATION AND EXTRACTION PIPELINE

### 6.1 Grobid: use it, but only for Latin script

Grobid's CRF/DeLFT models are trained on Latin-script scholarly PDFs. It will **run** on Chinese, Arabic and Persian PDFs without crashing, but header parsing, affiliation parsing and reference parsing return **plausible-looking wrong output** — the worst failure mode. Body segmentation via the PDF's own text layer can still be usable *if* a text layer exists with sane font encoding.

**It usually doesn't.** CNKI CAJ-converted PDFs, older Iranian journal PDFs and scanned AES bulletins are image-only or have broken CID mappings. **Verdict: Grobid for Latin-script only; route everything else to an OCR-first pipeline.**

### 6.2 OCR — tested recommendations by script

| Script | Recommendation | Notes |
|---|---|---|
| **Chinese (simp + trad)** | **MinerU** (`https://github.com/opendatalab/MinerU`, pkg `magic-pdf`) **[M]** | Built by a Chinese lab explicitly for Chinese scientific PDFs; layout + table + formula + OCR in one pass. **Best choice for a CNKI/Magtech corpus.** Fallback: **PaddleOCR** PP-OCRv4/v5 + **PP-Structure** for table-to-HTML **[H]** |
| **Japanese / Korean** | PaddleOCR (`lang='japan'`, `lang='korean'`) **[M]** | Solid |
| **Arabic / Persian** | **PaddleOCR (`lang='ar'`, `lang='fa'`)** or **Surya** **[M]** | **Tesseract `ara`/`fas` is poor on ligatured print — do not rely on it.** Expect to hand-check |
| **Turkish / Spanish / Portuguese / Russian** | Tesseract 5 with `tessdata_best` (`tur`, `spa`, `por`, `rus`) **[H]**, or Surya | Latin/Cyrillic is a solved problem |
| **General mixed corpus + tables** | **Surya** (`https://github.com/VikParuchuri/surya`, 90+ languages: OCR + layout + reading order + table recognition) paired with **Marker** (PDF→Markdown) **[M]**; or **Docling** (IBM, `https://github.com/docling-project/docling`) **[M]** as the orchestration layer with pluggable OCR backends | Docling is the right *framework* choice; Surya/Paddle/MinerU are the right *engine* choices |

**The RTL problem, concretely:** OCR emits logical order; many PDF text layers store **visual** order; naive concatenation reverses digit strings inside Arabic/Persian text. Pipeline: OCR → normalise presentation forms to base letters (NFKC) → `arabic_reshaper` + `python-bidi` only for *display*, never for *indexing* → transliterate numerals to ASCII **before** any numeric parsing. **Validation check that catches this cheaply: assert that extracted axis tick values are monotonic.** If they aren't, you have a bidi reversal.

### 6.3 Machine translation — the recommendation is *don't*

Do not MT full documents. Translate nothing for the extraction path.

For **triage** (deciding which PDFs to spend extraction effort on), the empirically better architecture is **skip MT entirely and classify in the source language with an LLM**. Modern frontier models read zh/ja/ko/ar/fa/tr/ru/es/pt/hi natively; translate-then-classify adds a lossy hop and reliably mangles exactly the technical terms you are keying on (中子仪, رطوبت‌سنج نوترونی, запасы влаги). Prompt in English, feed native title + abstract + figure captions + table captions, ask for a structured verdict (`has_multidepth_soil_water: bool`, `depths_cm: [...]`, `irrigated: bool`, `measurement_method: enum`, `data_location: table|figure|both|none`).

If you need a local/offline MT fallback for cost reasons: **NLLB-200** (`facebook/nllb-200-distilled-600M` or `-1.3B`, 200 languages, HuggingFace) **[H]**. Use it only on titles and abstracts.

### 6.4 Figure digitisation — where the real failure modes are

**Eastern Arabic-Indic (٠١٢٣٤٥٦٧٨٩, U+0660–0669) and Persian (۰۱۲۳۴۵۶۷۸۹, U+06F0–06F9) numerals on axis ticks are a confirmed digitizer killer.** So are the Persian decimal separator ٫ (U+066B) and thousands separator ٬ (U+066C). CJK axis *titles* (土壤含水率/%) are a smaller problem because tick labels in Chinese papers are usually ASCII digits — but the **units and the depth legend are in Chinese**, and getting the unit wrong (质量 vs 体积 含水率) silently corrupts your target variable by a factor of ~1.5.

**Tested recommendation — a hybrid, and this is the key design decision:**

1. **Do not OCR the figure.** Pass the cropped figure image to a **VLM** (Claude/GPT-4o class) and ask it for: axis variable names, units, min/max of each axis, tick values, series legend entries, and the measurement depths — as JSON. VLMs handle CJK axis text and Arabic-Indic numerals dramatically better than any OCR engine on this specific task, because they use context (a soil-moisture y-axis running 0.05–0.45 constrains the reading).
2. **Trace the curves with a classical digitizer** calibrated from the VLM-supplied axis anchors: **WebPlotDigitizer** (`https://automeris.io/WebPlotDigitizer`) **[H]** for human-in-the-loop, `plotdigitizer` (PyPI) **[M]** for scripted runs.
3. **Do not use `google/deplot`** (pix2struct) for final values — it produces plausible tables with poor numeric precision. It is fine as a *triage* signal ("does this figure plot θ against time at multiple depths?"), not as a data source.
4. **Validate every digitized series** against physics: 0 ≤ θ_v ≤ porosity (~0.55); θ at depth should be smoother than θ near the surface; post-irrigation rises must precede drydowns. Reject series that fail.

### 6.5 The extraction schema this all has to feed

Non-negotiable fields, because the multilingual literature is inconsistent in exactly these places:

```
value, unit, basis ∈ {volumetric_cm3cm3, volumetric_pct, gravimetric_pct, storage_mm},
depth_top_cm, depth_bottom_cm, method ∈ {gravimetric, neutron, TDR, FDR/capacitance,
  tensiometer_converted, COSMOS, unknown}, bulk_density_g_cm3 (nullable),
date, lat, lon, geolocation_precision, irrigation_system, irrigation_amount_mm,
crop, source_language, source_type ∈ {journal, thesis, station_report, tecdoc, dataset},
extraction_route ∈ {table, figure_digitized, native_data}, extraction_confidence
```

Russian `запасы влаги` (mm/layer) and Chinese 质量含水率 (gravimetric %) **cannot be converted to θ_v without bulk density**. Record them as-is with `bd=null` rather than fabricating a conversion; a large fraction of your non-English corpus will land here.

---

## 7. DELIVERABLE — RANKED BY YIELD PER UNIT EFFORT

**Tier S — do these first, they beat the entire literature sweep**

| # | Source | Programmatic? | Expected yield | Effort |
|---|---|---|---|---|
| 1 | **ISMN** (`ismn.earth`, `ismn` pkg) | ✅ Full | Very high — harmonized multi-depth θ, thousands of stations | Days |
| 2 | **TPDC / HiWATER Heihe** (`data.tpdc.ac.cn/en`) | ✅ Registered download | Very high — irrigated-oasis maize networks, 4–120 cm | Days |
| 3 | **CGSpace** OAI + DSpace7 REST | ✅ Full | High — CGIAR grey lit, 120k items | Days |
| 4 | **Dataverse constellation** (ICRISAT, ICARDA MEL, CIMMYT, Harvard/IRRI) via `pyDataverse` | ✅ Full, one client | High — ICRISAT Vertisol & ICARDA Tel Hadya neutron profiles | Days |
| 5 | **IAEA INIS + TECDOC series** | ⚠️ Partial (predictable PDF paths; search API unverified) | High — 40-country neutron-probe CRPs, English, free | 1–2 weeks |

**Tier A — the core of the non-English/grey sweep**

| # | Source | Programmatic? | Yield | Effort |
|---|---|---|---|---|
| 6 | **Shodhganga** OAI + **KrishiKosh** | ✅ OAI (verify) | Very high — 550k+ English theses with appendix tables | 1–2 weeks |
| 7 | **AGRIS** | ⚠️ API unverified; bulk XML on request | Very high if the API exists — built for this exact gap | 1 week + FAO email |
| 8 | **US land-grant IRs** via OpenDOAR/ROAR → `/do/oai/` + `/oai/request` | ✅ Full, one harvester | Very high — theses + AES field-day reports, English | 1–2 weeks |
| 9 | **journals.ekb.eg** per-journal OAI | ✅ OJS pattern | High — Nile Delta irrigated profiles, much in English | 1 week |
| 10 | **AICRP-IWM annual reports** (iiwm.icar.gov.in) | ⚠️ Manual/scrape | Very high density, near-zero competition | 1–2 weeks |
| 11 | **SciELO ArticleMeta** (`articlemetaapi`, `xylose`) | ✅ Full | High — Brazilian/Mexican/Chilean irrigation | Days |
| 12 | **Embrapa Alice + Infoteca-e** OAI | ✅ OAI | High — Semiárido/Cerrados irrigation bulletins | Days |
| 13 | **OpenAIRE Graph** dumps (Zenodo) | ✅ Full | High — free coverage of LA Referencia, IRDB, DergiPark | Days |
| 14 | **Chinese society journal sites** (tcsae.org, jid.net.cn, ecoagri.ac.cn) — Magtech scraping | ⚠️ Scrape | **Very high** — 膜下滴灌 Xinjiang cotton is the largest single block | 3–4 weeks + Chinese reader |

**Tier B — worthwhile, real friction**

| # | Source | Programmatic? | Yield | Effort |
|---|---|---|---|---|
| 15 | **Internet Archive + HathiTrust HTRC** for AES bulletins | ✅ Full-text search APIs | Moderate-high, historical | 1–2 weeks |
| 16 | **Iranian OJS journals** per-journal `/oai` | ✅ if pattern holds | High — Iran is a top-5 producer of this literature | 2 weeks + Persian reader |
| 17 | **DergiPark / TR Dizin** | ⚠️ Endpoints unverified | Moderate-high — GAP irrigated cotton | 1–2 weeks |
| 18 | **J-STAGE Web API** | ✅ Free, no key | Moderate (paddy-diluted; filter 畑地灌漑) | Days |
| 19 | **CyberLeninka** OAI/API | ⚠️ Semi | Moderate — Central Asian cotton irrigation | 1 week |
| 20 | **Theses.fr** API | ✅ | Moderate — Sahel/Maghreb via CIRAD/IRD | Days |
| 21 | **CAB Abstracts** (if subscribed) | ❌ Manual/licensed | High-quality English-abstract triage layer over non-English lit | Library negotiation |
| 22 | **LA Referencia / Redalyc / INTA** OAI | ✅ (verify) | Moderate, overlaps SciELO | Days |
| 23 | **YÖK Tez** | ⚠️ Hard scrape | High per-document, high friction | 2–3 weeks |
| 24 | **openknowledge.fao.org** OAI | ✅ | Low-moderate (reference, not raw data) | Days |
| 25 | **NAL AGRICOLA / Ag Data Commons** | ⚠️ Figshare API for ADC | Moderate | Days |
| 26 | **KCI / ScienceON** APIs | ✅ Keyed | Low-moderate (paddy) | Days |
| 27 | **ICID congress proceedings** | ❌ Manual | Moderate, scattered | 1–2 weeks manual |
| 28 | **EThOS CC0 metadata dump** → resolve to university IRs | ✅ | Moderate | Days |

**Tier C — do not attempt (blunt)**

| Source | Why not |
|---|---|
| **CNKI / Wanfang / VIP bulk harvest** | No API, ToS-prohibited, unstable overseas access, CAJ format, geopolitically fraught. **A US-based researcher should not attempt this. Get a Chinese collaborator or an institutional partnership, or stay on the society journal sites.** |
| **eLIBRARY.RU** | No API, anti-bot, sanctions complexity on payment. Use CyberLeninka instead. |
| **IranDoc Ganj full text** | Requires Iranian national ID. Closed. Use the OA journals. |
| **ProQuest PQDT bulk** | TDM Studio subscription only, no raw export. One-off PDFs are fine; bulk is a procurement project, not an engineering one. |
| **Magiran / Noormags paid content** | Paywalled + OFAC payment issues. Not worth it when SID.ir and the OJS journals are free. |
| **Indian Citation Index** | Commercialized/unstable, negligible marginal coverage over Shodhganga + epubs.icar.org.in. |
| **AGORA** | You are ineligible; it is an access programme, not an index. Delete from the plan. |
| **AQUASTAT as a θ source** | Contains no in-situ soil moisture. Use for stratification weights only. |
| **Hindi/Bengali/Tamil/Marathi query expansion** | Indian research is published in English. Zero marginal recall for real effort. |
| **Extension fact sheets at scale** | Recommendations, not measurements. Target field-day *research* reports instead. |

**Where you genuinely need a collaborator who reads the language:** Chinese (non-negotiable — it is the largest pool and the least accessible), Persian (second-largest, and the normalisation traps are severe), Turkish (moderate). Spanish, Portuguese, Russian and Arabic are tractable solo with the pipeline in §6 because the OA infrastructure is good and the terminology is short. Japanese and Korean are not worth a collaborator given the paddy dilution.

---

## 8. THE FIVE THINGS TO VERIFY BEFORE WRITING ANY CODE

Every one of these is a ten-second `curl`, and each gates a multi-week workstream:

1. `curl -s 'https://shodhganga.inflibnet.ac.in/oai/request?verb=Identify'` — gates Tier A #6, the largest thesis pool.
2. Open `https://agris.fao.org/search/en?query=soil+moisture` with devtools open and record the XHR URL — gates Tier A #7.
3. `curl -s 'https://api.jstage.jst.go.jp/searchapi/do?service=3&keyword=土壌水分&count=5'` — confirms the parameter set I recalled.
4. `curl -s 'https://newprairiepress.org/do/oai/?verb=Identify'` — confirms the Digital Commons pattern, which unlocks ~15 land-grant repositories at once.
5. `curl -s 'https://jsw.um.ac.ir/oai?verb=Identify'` — confirms the Iranian OJS pattern, which unlocks the whole Iranian tier.

---

**Sources:** none — the session's WebSearch quota (200/200) was exhausted before this subtask could issue a single query, so no search results back any statement above. All URLs, sizes, endpoints and API shapes are recalled from training data and carry the [H]/[M]/[L] confidence markers inline. Treat every [L] as a hypothesis and every [M] as needing a one-line `curl` before it enters a build plan.