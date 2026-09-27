"""
Rule-based parser that turns a plain-text master resume into a structured
JSON shape (contact / summary / skills / experience / education / projects).

This is intentionally heuristic rather than ML-based: no external model
download, fully deterministic, and easy for a human to audit. It will not
be perfect on every resume layout -- that's why the parsed structure is
stored and editable via PUT /resume-engine/master/parsed before it's ever
used to generate a tailored resume. Nothing here invents content; it only
reorganizes what's already in the raw text.
"""
import re

SECTION_ALIASES = {
    "summary": ["summary", "profile", "objective", "about"],
    "skills": ["skills", "technical skills", "core competencies", "technologies"],
    "experience": ["experience", "work experience", "professional experience", "employment history"],
    "education": ["education", "academic background"],
    "projects": ["projects", "personal projects", "key projects"],
    "certifications": ["certifications", "certificates", "licenses"],
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{7,}\d)")
LINKEDIN_RE = re.compile(r"(https?://)?(www\.)?linkedin\.com/\S+", re.IGNORECASE)
GITHUB_RE = re.compile(r"(https?://)?(www\.)?github\.com/\S+", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*[-•*▪●]\s*(.*)")


def _find_section_boundaries(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return list of (canonical_section_name, start_line, end_line) exclusive of headers."""
    header_positions = []
    for i, line in enumerate(lines):
        clean = line.strip().strip(":").lower()
        if not clean or len(clean) > 40:
            continue
        for canonical, aliases in SECTION_ALIASES.items():
            if clean in aliases or (clean.isupper() and clean.lower() in aliases):
                header_positions.append((canonical, i))
                break

    boundaries = []
    for idx, (name, start) in enumerate(header_positions):
        end = header_positions[idx + 1][1] if idx + 1 < len(header_positions) else len(lines)
        boundaries.append((name, start + 1, end))
    return boundaries


def _extract_contact(text: str, lines: list[str]) -> dict:
    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    linkedin_match = LINKEDIN_RE.search(text)
    github_match = GITHUB_RE.search(text)

    # Best-effort: the candidate's name is usually the first non-empty line
    name = next((l.strip() for l in lines[:5] if l.strip()), None)

    return {
        "name": name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "linkedin": linkedin_match.group(0) if linkedin_match else None,
        "github": github_match.group(0) if github_match else None,
    }


def _parse_skills_block(block_lines: list[str]) -> list[str]:
    text = " ".join(block_lines)
    # split on commas, bullets, pipes, semicolons
    raw_items = re.split(r"[,;|•\n]", text)
    skills = [item.strip(" -*\t") for item in raw_items if item.strip(" -*\t")]
    # de-dupe while preserving order
    seen = set()
    result = []
    for s in skills:
        key = s.lower()
        if key not in seen and 1 <= len(s) <= 60:
            seen.add(key)
            result.append(s)
    return result


def _parse_bulleted_entries(block_lines: list[str]) -> list[dict]:
    """
    Generic parser for experience/project/education blocks: groups lines into
    entries, where a non-bulleted line starts a new entry (title/company/date
    line) and subsequent bulleted lines are that entry's bullet points.
    """
    entries: list[dict] = []
    current = None

    for raw_line in block_lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        bullet_match = BULLET_RE.match(line)
        if bullet_match:
            if current is None:
                current = {"header": "", "bullets": []}
                entries.append(current)
            current["bullets"].append(bullet_match.group(1).strip())
        else:
            current = {"header": line.strip(), "bullets": []}
            entries.append(current)

    return entries


def _split_header(header: str) -> dict:
    """
    Best-effort split of a header line like:
      "Backend Engineer, Acme Corp | Jan 2022 - Present"
    into title / organization / dates. Falls back gracefully if the format
    doesn't match -- the full header text is always preserved.
    """
    dates = None
    date_match = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|\d{4})\s*[-–—to]+\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|\d{4}|Present|Current)",
        header,
        re.IGNORECASE,
    )
    if date_match:
        dates = date_match.group(0)
        header_wo_dates = header.replace(dates, "").strip(" |,-")
    else:
        header_wo_dates = header

    parts = re.split(r"[,|]| at ", header_wo_dates)
    parts = [p.strip() for p in parts if p.strip()]
    title = parts[0] if parts else header_wo_dates
    organization = parts[1] if len(parts) > 1 else None

    return {"raw_header": header, "title": title, "organization": organization, "dates": dates}


def parse_master_resume(raw_text: str) -> dict:
    lines = raw_text.splitlines()
    boundaries = _find_section_boundaries(lines)
    sections = {name: lines[start:end] for name, start, end in boundaries}

    contact = _extract_contact(raw_text, lines)

    summary_lines = sections.get("summary", [])
    summary = " ".join(l.strip() for l in summary_lines if l.strip())

    skills = _parse_skills_block(sections.get("skills", []))

    experience_raw = _parse_bulleted_entries(sections.get("experience", []))
    experience = [
        {**_split_header(e["header"]), "bullets": e["bullets"]} for e in experience_raw if e["header"] or e["bullets"]
    ]

    projects_raw = _parse_bulleted_entries(sections.get("projects", []))
    projects = [
        {"name": e["header"], "bullets": e["bullets"]} for e in projects_raw if e["header"] or e["bullets"]
    ]

    education_raw = _parse_bulleted_entries(sections.get("education", []))
    education = [
        {**_split_header(e["header"]), "bullets": e["bullets"]} for e in education_raw if e["header"] or e["bullets"]
    ]

    certifications_lines = sections.get("certifications", [])
    certifications = [l.strip(" -*\t") for l in certifications_lines if l.strip()]

    return {
        "contact": contact,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
        "projects": projects,
        "certifications": certifications,
    }
