"""Cross-lingual search terms, and the normalisation that makes them work.

Most of the world's irrigated soil water measurements were not written in
English. China, Iran, Turkey, Brazil and the Spanish-speaking world all have
large irrigation research literatures with profile data, indexed in databases
OpenAlex barely touches. Searching them needs the terms — and, more than the
terms, the normalisation, because in several of these scripts the *same word* is
stored several ways and a naive exact match silently returns nothing.

The failures are specific and each has a fix:

**Persian** stores the same word with Arabic ي (U+064A) or Persian ی (U+06CC),
and with Arabic ك (U+0643) or Persian ک (U+06A9), inconsistently across Iranian
databases. Zero-width non-joiners appear inside common compounds like قطره‌ای.

**Turkish** has the dotted/dotless i: `"SULAMA".lower()` gives `"sulama"` but
`"SULAMA".lower()` on a Turkish locale gives a different result for I, and
`"I".lower()` should be `"ı"`. A naive lowercase corrupts Turkish tokens — the
classic Turkish-I bug — and indexes frequently strip ğüşıöç entirely.

**Arabic** scanned-PDF text layers are full of presentation forms (U+FB50–FDFF,
U+FE70–FEFF) that look identical and do not match their base letters.

**Portuguese** splits Brazilian and European orthography on exactly the words
that matter: umidade/humidade, irrigação/rega, nêutrons/neutrões.

**Chinese** uses 质量含水率 (gravimetric) and 体积含水率 (volumetric) in roughly
equal measure, which is a units problem as much as a search one.

The term lists here are a seed to sanity-check against. The scalable source is
AGROVOC, which carries expert-curated labels for agricultural concepts in forty
languages and is maintained; :func:`agrovoc_sparql_query` builds the query.
"""

from __future__ import annotations

import re
import unicodedata

#: Soil moisture, irrigation, depth and instrument terms by language.
#: Seeded from a literature survey; verify and extend from AGROVOC.
TERMS: dict[str, dict[str, tuple[str, ...]]] = {
    "zh": {
        "moisture": ("土壤水分", "土壤含水率", "土壤含水量", "土壤水分含量",
                     "体积含水率", "质量含水率", "土壤储水量", "土壤水分动态"),
        "irrigation": ("灌溉", "灌水", "灌区", "节水灌溉", "膜下滴灌", "滴灌",
                       "地下滴灌", "喷灌", "微灌", "沟灌", "畦灌", "灌溉制度",
                       "亏缺灌溉", "调亏灌溉"),
        "depth": ("土壤剖面", "剖面", "土层", "不同土层深度", "垂直分布"),
        "instrument": ("中子仪", "中子水分仪", "中子管", "时域反射仪",
                       "频域反射", "土壤水分传感器", "烘干法", "张力计"),
    },
    "fa": {
        "moisture": ("رطوبت خاک", "محتوای آب خاک", "مقدار آب خاک",
                     "رطوبت حجمی", "رطوبت وزنی"),
        "irrigation": ("آبیاری", "آبیاری قطره‌ای", "آبیاری بارانی",
                       "آبیاری جویچه‌ای", "آبیاری نشتی", "آبیاری غرقابی",
                       "کم‌آبیاری", "آبیاری سطحی", "شبکه آبیاری"),
        "depth": ("پروفیل خاک", "نیمرخ خاک", "عمق خاک", "لایه‌های خاک",
                  "اعماق مختلف خاک"),
        "instrument": ("رطوبت‌سنج نوترونی", "نوترون‌متر", "تانسیومتر"),
    },
    "tr": {
        "moisture": ("toprak nemi", "toprak su içeriği", "toprak nem içeriği",
                     "hacimsel su içeriği"),
        "irrigation": ("sulama", "damla sulama", "yağmurlama sulama",
                       "karık sulama", "salma sulama", "kısıtlı sulama",
                       "kısıntılı sulama", "sulama programı", "sulama suyu"),
        "depth": ("toprak profili", "toprak derinliği", "toprak katmanı"),
        "instrument": ("nötron probu", "nötronmetre", "tansiyometre"),
    },
    "es": {
        "moisture": ("humedad del suelo", "contenido de agua en el suelo",
                     "contenido hídrico del suelo", "contenido volumétrico de agua"),
        "irrigation": ("riego", "riego por goteo", "riego por aspersión",
                       "riego por surcos", "riego por inundación",
                       "riego deficitario", "lámina de riego"),
        "depth": ("perfil del suelo", "profundidad del suelo", "capas del suelo"),
        "instrument": ("sonda de neutrones", "tensiómetro",
                       "reflectometría en el dominio del tiempo"),
    },
    "pt": {
        # Both orthographies, always. The BR/PT split falls on exactly the words
        # that carry the query.
        "moisture": ("umidade do solo", "humidade do solo", "teor de água no solo",
                     "conteúdo de água no solo", "umidade volumétrica"),
        "irrigation": ("irrigação", "rega", "irrigação por gotejamento",
                       "irrigação por aspersão", "irrigação por sulcos",
                       "irrigação deficitária"),
        "depth": ("perfil do solo", "profundidade do solo", "camadas do solo"),
        "instrument": ("sonda de nêutrons", "sonda de neutrões", "tensiômetro",
                       "tensiómetro"),
    },
    "ar": {
        "moisture": ("رطوبة التربة", "المحتوى المائي للتربة", "محتوى الماء في التربة"),
        "irrigation": ("الري", "الري بالتنقيط", "الري بالرش", "الري السطحي",
                       "الري بالغمر", "الري الناقص"),
        "depth": ("قطاع التربة", "المقطع الرأسي للتربة", "أعماق التربة", "طبقات التربة"),
        "instrument": ("مسبار النيوترون", "جهاز النيوترون"),
    },
    "ru": {
        "moisture": ("влажность почвы", "влагосодержание почвы",
                     "запасы влаги в почве"),
        "irrigation": ("орошение", "полив", "капельное орошение", "дождевание",
                       "бороздковый полив", "дефицитное орошение"),
        "depth": ("почвенный профиль", "горизонты почвы", "слой почвы"),
        "instrument": ("нейтронный влагомер",),
    },
    "ja": {
        # All three orthographies of "irrigation" are in active use and a query
        # using one misses the other two.
        "moisture": ("土壌水分", "土壌含水率", "体積含水率"),
        "irrigation": ("灌漑", "潅漑", "かんがい", "畑地灌漑", "点滴灌漑", "滴下灌漑"),
        "depth": ("土層", "深さ別", "土壌断面"),
        "instrument": ("中性子水分計",),
    },
    "ko": {
        "moisture": ("토양수분", "토양 수분함량", "용적수분함량"),
        "irrigation": ("관개", "점적관수", "밭관개"),
        "depth": ("토양단면", "토심", "깊이별"),
        "instrument": ("중성자 수분계",),
    },
}

#: Languages where the research is published in English anyway, so translating
#: the query wastes effort. Indian agricultural research is the clearest case:
#: Hindi-language agronomy publishing is extension-style and carries no raw
#: profile data, and the effort belongs in Shodhganga and KrishiKosh instead.
SKIP_LANGUAGES: dict[str, str] = {
    "hi": "Indian agricultural research publishes in English; target Shodhganga, "
          "KrishiKosh and AICRP reports instead",
    "bn": "as Hindi",
    "ta": "as Hindi",
    "te": "as Hindi",
    "mr": "as Hindi",
}


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
ARABIC_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})
TASHKEEL = re.compile(r"[ً-ْٰـ]")
ZWNJ = "‌"


def normalize_persian(text: str) -> str:
    """Fold the Arabic/Persian character variants and strip diacritics.

    Iranian databases store the same word both ways; without this, exact
    matching returns a fraction of what exists.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(ARABIC_TO_PERSIAN)
    return TASHKEEL.sub("", text).strip()


def normalize_arabic(text: str) -> str:
    """Fold alef forms, strip diacritics, and flatten presentation forms.

    NFKC is what converts the U+FB50–FDFF and U+FE70–FEFF presentation forms
    that fill scanned-PDF text layers back into base letters. They render
    identically and do not match without it.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(ARABIC_ALEF)
    return TASHKEEL.sub("", text).strip()


def normalize_turkish(text: str) -> str:
    """Lowercase Turkish correctly.

    Python's ``str.lower()`` maps I to i, but Turkish I lowercases to ı and İ
    lowercases to i. Getting this wrong corrupts every token containing the
    letter — the classic Turkish-I bug.
    """
    return text.replace("I", "ı").replace("İ", "i").lower()


ASCII_FOLD = str.maketrans({
    "ğ": "g", "ü": "u", "ş": "s", "ı": "i", "ö": "o", "ç": "c",
    "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n",
    "ã": "a", "õ": "o", "â": "a", "ê": "e", "ô": "o", "à": "a",
})


def ascii_fold(text: str) -> str:
    """Strip diacritics. Authors and indexers frequently enter metadata this way."""
    folded = text.translate(ASCII_FOLD)
    return "".join(
        c for c in unicodedata.normalize("NFD", folded)
        if unicodedata.category(c) != "Mn"
    )


def normalize(text: str, language: str) -> str:
    """Apply the right normalisation for a language."""
    if not text:
        return ""
    if language == "fa":
        return normalize_persian(text)
    if language == "ar":
        return normalize_arabic(text)
    if language == "tr":
        return normalize_turkish(text)
    return unicodedata.normalize("NFKC", text).strip()


def variants(term: str, language: str) -> list[str]:
    """Every spelling of a term that a database might hold.

    Persian and Arabic get a zero-width-non-joiner family, because the same
    compound appears with the joiner, without it, and with a space. Turkish and
    the Romance languages get an ASCII-folded form. Korean gets spaced and
    unspaced forms, since Korean spacing is not standardised.
    """
    out = {term}
    normalized = normalize(term, language)
    out.add(normalized)

    if language in ("fa", "ar"):
        out.add(normalized.replace(ZWNJ, ""))
        out.add(normalized.replace(ZWNJ, " "))
    if language in ("tr", "es", "pt"):
        out.add(ascii_fold(normalized))
        out.add(ascii_fold(normalized).lower())
    if language == "ko":
        out.add(normalized.replace(" ", ""))
    if language == "zh":
        try:
            from opencc import OpenCC

            out.add(OpenCC("s2t").convert(normalized))
        except ImportError:
            pass  # traditional variants unavailable without opencc

    return sorted(v for v in out if v)


def query_terms(language: str, categories: tuple[str, ...] = ("moisture", "irrigation")) -> list[str]:
    """Every variant of every seed term for a language."""
    if language in SKIP_LANGUAGES:
        raise ValueError(f"{language} is deliberately not targeted: {SKIP_LANGUAGES[language]}")
    if language not in TERMS:
        raise KeyError(f"no seed terms for {language!r}; known: {sorted(TERMS)}")
    out: set[str] = set()
    for category in categories:
        for term in TERMS[language].get(category, ()):
            out.update(variants(term, language))
    return sorted(out)


def build_query(language: str, joiner: str = " OR ") -> str:
    """A boolean query pairing moisture terms with irrigation terms."""
    moisture = query_terms(language, ("moisture",))
    irrigation = query_terms(language, ("irrigation",))
    quote = lambda terms: joiner.join(f'"{t}"' if " " in t else t for t in terms)  # noqa: E731
    return f"({quote(moisture)}) AND ({quote(irrigation)})"


def agrovoc_sparql_query(concept_label: str = "soil water content") -> str:
    """SPARQL that pulls every language's labels for a concept from AGROVOC.

    The maintained, expert-curated alternative to the hand-seeded lists above:
    AGROVOC carries preferred and alternate labels in forty-plus languages and is
    updated, where a hand translation is neither. Run against
    ``https://agrovoc.fao.org/sparql``.
    """
    return f"""
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?concept ?label ?lang WHERE {{
  ?concept a skos:Concept ;
           skos:prefLabel ?en .
  FILTER(lang(?en) = "en" && LCASE(STR(?en)) = "{concept_label.lower()}")
  ?concept (skos:prefLabel|skos:altLabel) ?label .
  BIND(LANG(?label) AS ?lang)
}}
""".strip()
