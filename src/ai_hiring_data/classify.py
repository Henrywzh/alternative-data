from __future__ import annotations

import re


CLASSIFIER_VERSION = "title-taxonomy-v2"

SENIORITY_LEVELS: tuple[str, ...] = (
    "Early career",
    "Individual contributor",
    "Senior / Staff / Principal",
    "Manager / Director / Executive",
    "Unspecified",
)

ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Safety / Policy", re.compile(r"\b(safety|alignment|responsible ai|policy|governance|trust|red team|preparedness)\b", re.I)),
    ("Research", re.compile(r"\b(research|scientist|fellow|residen(?:t|cy)|postdoc)\b", re.I)),
    ("AI / ML", re.compile(r"\b(machine learning|ml|artificial intelligence|ai|model|inference|training|evals?|data scientist|applied)\b", re.I)),
    ("Engineering / Infrastructure", re.compile(r"\b(engineer|developer|infrastructure|systems|distributed|cloud|network|hardware|silicon|compute|gpu|performance|reliability|security|database|storage|devops|sre)\b", re.I)),
    ("Product / Design", re.compile(r"\b(product|design|designer|user experience|ux|program manager|technical program)\b", re.I)),
    ("Sales / GTM", re.compile(r"\b(sales|account executive|business development|marketing|growth|go.to.market|gtm|customer success|solutions architect|partnerships)\b", re.I)),
    ("Operations", re.compile(r"\b(operations|recruit|talent|people|finance|legal|counsel|workplace|facilities|procurement|human resources|hr|chief of staff)\b", re.I)),
)

AI_ROLE_PATTERN = re.compile(
    r"\b(ai|ml|machine learning|artificial intelligence|deep learning|research scientist|research engineer|model(?:ing)?|inference|training|alignment|evals?|robotics|computer vision|natural language|nlp)\b",
    re.I,
)


def classify_role(title: str, department: str | None = None, team: str | None = None) -> tuple[str, bool, str, str]:
    title_text = str(title or "").strip()
    context = " ".join(value for value in (title_text, str(department or ""), str(team or "")) if value).strip()
    role_family = "Other"
    for label, pattern in ROLE_PATTERNS:
        if pattern.search(context):
            role_family = label
            break
    title_match = bool(AI_ROLE_PATTERN.search(title_text))
    context_match = bool(AI_ROLE_PATTERN.search(context))
    confidence = "high" if title_match else "medium" if context_match else "not_classified"
    return role_family, context_match, confidence, CLASSIFIER_VERSION


def classify_seniority(title: str) -> str:
    value = str(title or "").strip()
    if re.search(r"\b(intern|internship|new grad|graduate|apprentice|entry.level|junior)\b", value, re.I):
        return "Early career"
    if re.search(
        r"\b(chief executive|chief technology|chief product|chief data|chief research|chief\s+\w+|c-suite|vp|vice president|head of|director|general manager|senior manager|people manager|manager|(?<!account )executive)\b",
        value,
        re.I,
    ):
        return "Manager / Director / Executive"
    if re.search(
        r"\b(lead|principal|staff|senior|sr\.?|architect|distinguished)\b",
        value,
        re.I,
    ):
        return "Senior / Staff / Principal"
    if re.search(
        r"\b(engineer|developer|scientist|researcher|designer|analyst|economist|technician|specialist|consultant)\b",
        value,
        re.I,
    ):
        return "Individual contributor"
    return "Unspecified"
