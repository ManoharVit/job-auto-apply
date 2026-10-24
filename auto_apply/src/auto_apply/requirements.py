"""Conservative checks for explicit skill and experience requirements."""
import html
import re
from html.parser import HTMLParser

SKILLS = (
    "Spring Boot", "SQLAlchemy", "PostgreSQL", "LangGraph", "LangChain",
    "Kubernetes", "Terraform", "Databricks", "Snowflake", "WebSockets",
    "FastAPI", "Django", "Flask", "Python", "Java", "Kafka", "Redis",
    "Celery", "Docker", "Git", "Airflow", "Dagster", "dbt", "Spark",
    "MySQL", "SQL", "AWS", "GCP", "Azure", "GraphQL", "asyncio",
    "TypeScript", "JavaScript", "Scala", "Rust",
    "LLM", "RAG", "NumPy", "scikit-learn", "Vertex AI", "BigQuery",
)

class _DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "li", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")


def description_text(value):
    text = str(value or "")
    if re.search(r"&lt;/?(?:p|div|li|ul|ol|h[1-6]|section|span)\b", text, re.I):
        text = html.unescape(text)
    parser = _DescriptionParser()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)

def _contains(skill, text):
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(skill.lower()) + r"(?![a-z0-9])", text.lower()))

PREFERRED = r"\b(?:nice[ -]to[ -]haves?|preferred|preferably|desirable|optional)\b"
MANDATORY = r"\b(?:must have|mandatory|required|requires|requirements|essential)\b"

def _clauses(description):
    """Keep requirement markers local to their clause, including on one line."""
    mode = False
    for line in description_text(description).splitlines():
        parts = re.split(
            r";|,(?=\s*[a-z])|\.\s+|\b(?:but|while)\b|\band\b(?!/)",
            line, flags=re.I,
        )
        for part in parts:
            preferred = bool(re.search(PREFERRED, part, re.I))
            mandatory = bool(re.search(MANDATORY, part, re.I)) and not re.search(r"\bnot required\b", part, re.I)
            if mandatory:
                mode = True
            elif preferred:
                mode = False
            yield part, mode and (mandatory or not preferred)

def mandatory_gaps(job, verified_skills):
    verified = [str(skill).lower() for skill in verified_skills]
    required = []
    explicit = job.get("required_skills") or []
    if isinstance(explicit, str):
        explicit = [value.strip() for value in explicit.split(",")]
    for skill in explicit:
        if skill and not any(_contains(str(skill), known) for known in verified):
            required.append(str(skill))
    for line, mandatory in _clauses(job.get("description")):
        if not mandatory:
            continue
        for clause in re.split(r"[,;]|\band\b(?!/)", line, flags=re.I):
            matches = sorted(
                [(match.start(), match.end(), skill) for skill in SKILLS
                 for match in re.finditer(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", clause, re.I)],
                key=lambda value: (value[0], -(value[1] - value[0])),
            )
            groups = []
            for start, end, skill in matches:
                if groups and re.fullmatch(r"\s*(?:/|or|and/or)\s*", clause[groups[-1][-1][1]:start], re.I):
                    groups[-1].append((start, end, skill))
                else:
                    groups.append([(start, end, skill)])
            for group in groups:
                names = [item[2] for item in group]
                if not any(_contains(name, known) for name in names for known in verified):
                    required.append(" or ".join(names))
    return list(dict.fromkeys(required))

def _experience_requirements(description):
    for line, _ in _clauses(description):
        if re.search(PREFERRED + r"|\b(?:company history|founded)\b", line, re.I):
            continue
        for match in re.finditer(
            r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:\+|[-–—]|to)?\s*(?:\d+(?:\.\d+)?)?\s*"
            r"(?:years?|yrs?)\b",
            line, re.I,
        ):
            # Skill-specific tenure is separate from total professional tenure.
            context = line
            next_number = re.search(r"\d+\s*(?:years?|yrs?)", context[match.end():], re.I)
            if next_number:
                context = context[:match.end() + next_number.start()]
            skills = [skill for skill in SKILLS if _contains(skill, context)]
            if not skills and not re.search(r"experience|professional|software|engineering|programming|building|develop|working", context, re.I):
                continue
            yield float(match.group(1)), skills

def required_experience_minima(description):
    return [years for years, _ in _experience_requirements(description)]

def skill_experience_gaps(description, screening):
    facts = screening.get("professional_experience_years", {})
    if not isinstance(facts, dict):
        facts = {}
    problems = []
    for years, skills in _experience_requirements(description):
        for skill in skills:
            declared = next((value for key, value in facts.items() if key.casefold() == skill.casefold()), None)
            try:
                import math
                if type(declared) is bool:
                    raise ValueError()
                declared = float(declared)
                if not math.isfinite(declared) or declared < years:
                    raise ValueError()
            except (ValueError, TypeError):
                problems.append(f"{years:g} professional years with {skill} (verified tool-specific tenure missing or insufficient)")
    return list(dict.fromkeys(problems))
