"""Deterministic RBAC topic gate — v0.10.

Problem (v0.9, recorded limitation): a Service user asking
"AML policy for high-risk customers?" got an answer stitched from
RETAIL chunks (the KYC chunk mentions high-risk customers) instead
of an RBAC refusal. The score-based probe in generation.py catches
most blocked topics, but it is probabilistic — it compares reranker
scores — so a question that merely shares words with an allowed
document can slip through.

This gate is deterministic and runs BEFORE any retrieval: if the
question matches a topic phrase that belongs to a department the
caller's role may NOT see, the question is refused immediately —
no retrieval, no reranking, no chance of a leak. The probe in
generation.py stays as a fallback for phrasings this map does not
cover.

Rules:
  * Matching is on the normalised question (lowercase, NFKD,
    punctuation -> spaces). Latin phrases match on whole words
    (``\\b``), so "sama" matches "SAMA compliance" but not a word
    that merely contains those letters; Arabic phrases match as
    substrings (Arabic has no word-boundary regex).
  * Only departments the role CANNOT see are gated. KYC and loans
    are RETAIL, so a Service user asking about KYC or a loan is
    NEVER gated — only COMPLIANCE topics (AML, money laundering,
    terrorist financing, SAMA, suspicious transactions, sanctions)
    and HR topics (leave, salary, HR policy, PDPL/privacy) are.
  * A question can match several topics; the first blocked
    department found is returned (order: COMPLIANCE, HR).
"""
import re
import unicodedata

# topic -> (department, latin phrases, arabic phrases)
TOPIC_RULES: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    (
        "compliance",
        "COMPLIANCE",
        (
            "aml", "anti-money laundering", "anti money laundering",
            "money laundering", "terrorist financing",
            "terrorism financing", "sama",
            "suspicious transaction", "suspicious activity",
            "cash transaction reporting", "reporting threshold",
            "sanctions", "sanction screening",
            "compliance policy", "compliance department",
        ),
        (
            "غسل الأموال", "مكافحة غسل الأموال", "تمويل الإرهاب",
            "ساما", "المعاملات المشبوهة", "الإبلاغ عن المعاملات",
            "عتبة الإبلاغ", "الامتثال",
        ),
    ),
    (
        "hr",
        "HR",
        (
            "annual leave", "leave policy", "sick leave",
            "maternity leave", "paternity leave",
            "salary", "payroll", "hr policy", "human resources",
            "employee benefits", "working hours", "overtime",
            "performance review", "resignation", "probation",
            "pdpl", "data privacy", "personal data protection",
            "privacy policy", "privacy summary",
        ),
        (
            "إجازة", "الإجازة", "الراتب", "الموارد البشرية",
            "ساعات العمل", "حماية البيانات", "البيانات الشخصية",
            "الخصوصية",
        ),
    ),
]

# "leave" alone is a real HR word ("how many days of leave..."), but
# as a bare substring it would also match "please leave a message".
# It is only gated as a whole word, and only in a question that also
# mentions employees/days/policy — handled by the word-boundary
# matcher plus the HR_CONTEXT check below.
_BARE_WORD_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("leave", "HR", ("employee", "employees", "days", "policy", "annual", "sick")),
]

_PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06FF]", re.UNICODE)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = _PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _phrase_matches(normalized: str, phrase: str) -> bool:
    """Whole-word match for Latin phrases, substring for Arabic ones.

    The phrase is normalised with the SAME function as the question:
    NFKD decomposes Arabic hamza letters (e.g. أ -> ا + combining
    hamza), so a composed phrase would never match decomposed
    question text without this step."""
    phrase = _normalize(phrase)
    if not phrase:
        return False
    if any("\u0600" <= ch <= "\u06FF" for ch in phrase):
        return phrase in normalized
    return re.search(r"\b" + re.escape(phrase) + r"\b", normalized) is not None


def gated_department(question: str, allowed_departments: list[str] | None) -> str | None:
    """Return the blocked department a question is about, or None.

    ``allowed_departments`` is the caller's list (None = no
    restriction, e.g. a direct call without a logged-in user — then
    nothing is gated). A topic only blocks when its department is
    NOT in the allowed list.
    """
    if allowed_departments is None:
        return None
    allowed = set(allowed_departments)
    normalized = _normalize(question)
    if not normalized:
        return None
    for _topic, department, latin, arabic in TOPIC_RULES:
        if department in allowed:
            continue
        for phrase in latin + arabic:
            if _phrase_matches(normalized, phrase):
                return department
    for word, department, context in _BARE_WORD_RULES:
        if department in allowed:
            continue
        if re.search(r"\b" + re.escape(word) + r"\b", normalized):
            if any(c in normalized for c in context):
                return department
    return None
