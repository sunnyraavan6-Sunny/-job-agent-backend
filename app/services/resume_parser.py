"""
Rule-based parser for the master resume.

The parser preserves the candidate's original resume facts and reorganizes
them into a structured JSON shape used by the resume engine.

Supported sections include:
- Profile Summary
- Technical Skills
- Experience
- Education
- Technical Projects
- Certifications
- Soft Skills
- Achievements

Nothing is invented by this parser.
"""

import re


SECTION_ALIASES = {
    "summary": [
        "summary",
        "profile",
        "profile summary",
        "objective",
        "career objective",
        "about",
    ],
    "skills": [
        "skills",
        "technical skills",
        "technical skill",
        "core competencies",
        "technologies",
    ],
    "experience": [
        "experience",
        "work experience",
        "professional experience",
        "employment history",
    ],
    "education": [
        "education",
        "academic background",
    ],
    "projects": [
        "projects",
        "technical projects",
        "technical project",
        "personal projects",
        "key projects",
    ],
    "certifications": [
        "certifications",
        "certificates",
        "licenses",
    ],
    "soft_skills": [
        "soft skills",
        "soft skill",
    ],
    "achievements": [
        "achievements",
        "achievement",
    ],
}


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

PHONE_RE = re.compile(
    r"(\+?\d[\d\-\s()]{7,}\d)"
)

LINKEDIN_RE = re.compile(
    r"(https?://)?(www\.)?linkedin\.com/\S+",
    re.IGNORECASE,
)

GITHUB_RE = re.compile(
    r"(https?://)?(www\.)?github\.com/\S+",
    re.IGNORECASE,
)

BULLET_RE = re.compile(
    r"^\s*[-•*▪◦]\s*(.*)"
)


def _normalize_header(line: str) -> str:
    """
    Normalize a section header for matching.

    Examples:
        PROFILE SUMMARY -> profile summary
        TECHNICAL PROJECTS: -> technical projects
    """
    return line.strip().strip(":").strip().lower()


def _find_section_boundaries(
    lines: list[str],
) -> list[tuple[str, int, int]]:
    """
    Find known resume section headers and return:

        (canonical_section_name, start_line, end_line)

    The header itself is excluded from the section content.
    """

    header_positions = []

    for i, line in enumerate(lines):
        clean = _normalize_header(line)

        if not clean or len(clean) > 50:
            continue

        for canonical, aliases in SECTION_ALIASES.items():
            if clean in aliases:
                header_positions.append((canonical, i))
                break

    boundaries = []

    for idx, (name, start) in enumerate(header_positions):
        if idx + 1 < len(header_positions):
            end = header_positions[idx + 1][1]
        else:
            end = len(lines)

        boundaries.append(
            (name, start + 1, end)
        )

    return boundaries


def _extract_contact(
    text: str,
    lines: list[str],
) -> dict:
    """
    Extract contact information from the complete resume text.
    """

    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    linkedin_match = LINKEDIN_RE.search(text)
    github_match = GITHUB_RE.search(text)

    # The candidate's name is normally the first non-empty line.
    name = next(
        (line.strip() for line in lines[:5] if line.strip()),
        None,
    )

    return {
        "name": name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "linkedin": linkedin_match.group(0) if linkedin_match else None,
        "github": github_match.group(0) if github_match else None,
    }


def _clean_item(value: str) -> str:
    """
    Remove common bullet/whitespace characters.
    """

    return value.strip(" -*•▪◦\t")


def _parse_skills_block(
    block_lines: list[str],
) -> list[str]:
    """
    Parse technical skills.

    Handles both:

        Python, SQL, Power BI

    and:

        Programming: Python
        Libraries: Pandas, NumPy, Matplotlib
        Databases: SQL/MySQL
        Data Visualization & BI: Power BI, Tableau, Excel
    """

    skills = []

    for raw_line in block_lines:
        line = _clean_item(raw_line)

        if not line:
            continue

        # Example:
        # Programming: Python
        # Libraries: Pandas, NumPy
        if ":" in line:
            _, value = line.split(":", 1)
            line = value.strip()

        # Normalize common separators.
        items = re.split(r"[,;|]", line)

        for item in items:
            item = _clean_item(item)

            if not item:
                continue

            # Preserve SQL/MySQL as separate useful skills.
            if "/" in item:
                slash_items = [
                    _clean_item(x)
                    for x in item.split("/")
                    if _clean_item(x)
                ]
            else:
                slash_items = [item]

            for skill in slash_items:
                if 1 <= len(skill) <= 80:
                    skills.append(skill)

    # De-duplicate while preserving original order.
    seen = set()
    result = []

    for skill in skills:
        key = skill.lower()

        if key not in seen:
            seen.add(key)
            result.append(skill)

    return result


def _parse_simple_list(
    block_lines: list[str],
) -> list[str]:
    """
    Parse sections such as soft skills and achievements.
    """

    result = []

    for raw_line in block_lines:
        line = _clean_item(raw_line)

        if not line:
            continue

        # If a line contains comma-separated items, preserve them as
        # individual entries.
        items = re.split(r"[,;|]", line)

        for item in items:
            item = _clean_item(item)

            if item:
                result.append(item)

    # De-duplicate while preserving order.
    seen = set()
    output = []

    for item in result:
        key = item.lower()

        if key not in seen:
            seen.add(key)
            output.append(item)

    return output


def _parse_bulleted_entries(
    block_lines: list[str],
) -> list[dict]:
    """
    Generic parser for experience/project/education blocks.

    A non-bulleted line starts a new entry.
    Bulleted lines following it become that entry's bullets.
    """

    entries = []
    current = None

    for raw_line in block_lines:
        line = raw_line.rstrip()

        if not line.strip():
            continue

        bullet_match = BULLET_RE.match(line)

        if bullet_match:
            if current is None:
                current = {
                    "header": "",
                    "bullets": [],
                }
                entries.append(current)

            current["bullets"].append(
                bullet_match.group(1).strip()
            )

        else:
            current = {
                "header": line.strip(),
                "bullets": [],
            }
            entries.append(current)

    return entries


def _split_header(header: str) -> dict:
    """
    Best-effort split of headers containing title, organization and dates.

    The complete original header is always preserved in raw_header.
    """

    dates = None

    date_match = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\.?\s*\d{4}|\d{4})"
        r"\s*[-–—to]+\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\.?\s*\d{4}|\d{4}|Present|Current)",
        header,
        re.IGNORECASE,
    )

    if date_match:
        dates = date_match.group(0)

        header_without_dates = header.replace(
            dates,
            "",
        ).strip(" |,-")

    else:
        header_without_dates = header

    parts = re.split(
        r"[,|]|\s+at\s+",
        header_without_dates,
    )

    parts = [
        part.strip()
        for part in parts
        if part.strip()
    ]

    title = (
        parts[0]
        if parts
        else header_without_dates
    )

    organization = (
        parts[1]
        if len(parts) > 1
        else None
    )

    return {
        "raw_header": header,
        "title": title,
        "organization": organization,
        "dates": dates,
    }


def parse_master_resume(
    raw_text: str,
) -> dict:
    """
    Convert raw master-resume text into structured JSON.

    The returned keys remain compatible with resume_builder.py while also
    preserving soft skills and achievements from the candidate's resume.
    """

    lines = raw_text.splitlines()

    boundaries = _find_section_boundaries(lines)

    sections = {
        name: lines[start:end]
        for name, start, end in boundaries
    }

    contact = _extract_contact(
        raw_text,
        lines,
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    summary_lines = sections.get(
        "summary",
        [],
    )

    summary = " ".join(
        line.strip()
        for line in summary_lines
        if line.strip()
    )

    # ------------------------------------------------------------------
    # Technical Skills
    # ------------------------------------------------------------------

    skills = _parse_skills_block(
        sections.get("skills", [])
    )

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------

    experience_raw = _parse_bulleted_entries(
        sections.get("experience", [])
    )

    experience = [
        {
            **_split_header(entry["header"]),
            "bullets": entry["bullets"],
        }
        for entry in experience_raw
        if entry["header"] or entry["bullets"]
    ]

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    projects_raw = _parse_bulleted_entries(
        sections.get("projects", [])
    )

    projects = [
        {
            "name": entry["header"],
            "bullets": entry["bullets"],
        }
        for entry in projects_raw
        if entry["header"] or entry["bullets"]
    ]

    # ------------------------------------------------------------------
    # Education
    # ------------------------------------------------------------------

    education_raw = _parse_bulleted_entries(
        sections.get("education", [])
    )

    education = [
        {
            **_split_header(entry["header"]),
            "bullets": entry["bullets"],
        }
        for entry in education_raw
        if entry["header"] or entry["bullets"]
    ]

    # ------------------------------------------------------------------
    # Certifications
    # ------------------------------------------------------------------

    certifications = _parse_simple_list(
        sections.get("certifications", [])
    )

    # ------------------------------------------------------------------
    # Soft Skills
    # ------------------------------------------------------------------

    soft_skills = _parse_simple_list(
        sections.get("soft_skills", [])
    )

    # ------------------------------------------------------------------
    # Achievements
    # ------------------------------------------------------------------

    achievements = _parse_simple_list(
        sections.get("achievements", [])
    )

    # ------------------------------------------------------------------
    # Final structured resume
    # ------------------------------------------------------------------

    return {
        "contact": contact,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
        "projects": projects,
        "certifications": certifications,
        "soft_skills": soft_skills,
        "achievements": achievements,
    }