"""
Resume parser for Kishore Kumar's master-resume format.

This parser is intentionally conservative:
- It preserves the original resume facts.
- It recognizes the actual section headings used in the resume.
- It handles PDF-extracted bullet characters such as ● and •.
- It preserves skill categories while extracting individual skills.
- It correctly groups the two technical projects.
"""

import re


SECTION_ALIASES = {
    "summary": {
        "summary",
        "profile",
        "profile summary",
        "objective",
        "career objective",
        "about",
    },
    "education": {
        "education",
        "academic background",
    },
    "skills": {
        "skills",
        "technical skills",
        "technical skill",
    },
    "projects": {
        "projects",
        "technical projects",
        "technical project",
        "personal projects",
        "key projects",
    },
    "soft_skills": {
        "soft skills",
        "soft skill",
    },
    "certifications": {
        "certifications",
        "certificates",
        "licenses",
    },
    "achievements": {
        "achievements",
        "achievement",
    },
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment history",
    },
}


EMAIL_RE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"
)

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


# Handles:
# ● text
# • text
# - text
# * text
BULLET_RE = re.compile(
    r"^\s*[●•▪◦\-*]\s*(.*)"
)


def _clean_line(line: str) -> str:
    """Normalize whitespace while preserving the actual text."""

    line = line.replace("\xa0", " ")
    line = line.replace("\t", " ")

    return re.sub(r"\s+", " ", line).strip()


def _normalize_header(line: str) -> str:
    """Normalize a section heading."""

    line = _clean_line(line)

    return line.strip(":").strip().lower()


def _find_sections(lines: list[str]) -> dict[str, list[str]]:
    """
    Locate known section headings and return their content.
    """

    positions = []

    for index, line in enumerate(lines):
        normalized = _normalize_header(line)

        if not normalized:
            continue

        for section_name, aliases in SECTION_ALIASES.items():
            if normalized in aliases:
                positions.append((section_name, index))
                break

    sections = {}

    for position, (section_name, start_index) in enumerate(positions):

        if position + 1 < len(positions):
            end_index = positions[position + 1][1]
        else:
            end_index = len(lines)

        sections[section_name] = lines[
            start_index + 1:end_index
        ]

    return sections


def _extract_contact(
    text: str,
    lines: list[str],
) -> dict:
    """Extract contact information."""

    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    linkedin_match = LINKEDIN_RE.search(text)
    github_match = GITHUB_RE.search(text)

    name = None

    for line in lines[:5]:
        cleaned = _clean_line(line)

        if cleaned:
            name = cleaned
            break

    return {
        "name": name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "linkedin": linkedin_match.group(0) if linkedin_match else None,
        "github": github_match.group(0) if github_match else None,
    }


def _remove_bullet(line: str) -> str:
    """Remove a leading bullet character."""

    match = BULLET_RE.match(line)

    if match:
        return match.group(1).strip()

    return _clean_line(line)


def _is_bullet(line: str) -> bool:
    """Check whether a line starts with a bullet."""

    return bool(BULLET_RE.match(line))


def _parse_skills(block_lines: list[str]) -> list[str]:
    """
    Parse the technical-skills section.

    Example source:

    Programming Languages: Python
    Libraries: Pandas, NumPy, Matplotlib, Seaborn
    Databases: SQL / MySQL (CTEs, window functions, joins, subqueries)
    Data Visualization & Business Intelligence:
        Power BI (DAX, data modeling), Tableau (basic), Excel (...)
    Business & Statistical Analysis:
        Exploratory data analysis, ...
    """

    skills = []

    for raw_line in block_lines:

        line = _remove_bullet(raw_line)

        if not line:
            continue

        # Remove category label.
        if ":" in line:
            category, value = line.split(":", 1)

            # Only treat it as a category when the left side looks like
            # a normal skill-category label.
            if len(category.strip()) <= 70:
                line = value.strip()

        if not line:
            continue

        # Remove duplicate whitespace.
        line = _clean_line(line)

        # Handle comma/semicolon/pipe-separated skills.
        items = re.split(r"[,;|]", line)

        for item in items:

            item = item.strip()

            if not item:
                continue

            # SQL / MySQL should become two searchable skills.
            if re.fullmatch(
                r"SQL\s*/\s*MySQL.*",
                item,
                re.IGNORECASE,
            ):
                skills.append("SQL")
                skills.append("MySQL")
                continue

            # Preserve parentheses because they contain useful
            # technical details such as DAX and data modeling.
            skills.append(item)

    # De-duplicate while preserving order.
    result = []
    seen = set()

    for skill in skills:

        key = skill.lower().strip()

        if key and key not in seen:
            seen.add(key)
            result.append(skill.strip())

    return result


def _parse_simple_list(
    block_lines: list[str],
) -> list[str]:
    """
    Parse simple list sections such as:

    Soft Skills
    Leadership | Team Collaboration | Problem Solving

    Certifications
    • Data Analytics Essentials — Cisco, 2026
    • Cambridge English B2
    """

    result = []

    for raw_line in block_lines:

        line = _remove_bullet(raw_line)

        if not line:
            continue

        # Pipe-separated values.
        if "|" in line:
            items = line.split("|")

        # Comma-separated values are only split for soft-skill style
        # lists. Certification text should remain intact.
        else:
            items = [line]

        for item in items:

            item = item.strip()

            if item:
                result.append(item)

    # De-duplicate.
    output = []
    seen = set()

    for item in result:

        key = item.lower()

        if key not in seen:
            seen.add(key)
            output.append(item)

    return output


def _parse_education(
    block_lines: list[str],
) -> list[dict]:
    """
    Parse the education block.

    Expected source:

    B. Tech – Information Technology    CGPA: 7.56/10
    Malla Reddy University             2021 – 2025
    """

    cleaned = [
        _clean_line(line)
        for line in block_lines
        if _clean_line(line)
    ]

    if not cleaned:
        return []

    title_line = cleaned[0]

    organization = (
        cleaned[1]
        if len(cleaned) > 1
        else None
    )

    dates = None

    date_match = re.search(
        r"\b\d{4}\s*[–—-]\s*\d{4}\b",
        " ".join(cleaned),
    )

    if date_match:
        dates = date_match.group(0)

    cgpa = None

    cgpa_match = re.search(
        r"CGPA\s*:\s*([0-9.]+\s*/\s*10)",
        title_line,
        re.IGNORECASE,
    )

    if cgpa_match:
        cgpa = cgpa_match.group(1)

    title = re.sub(
        r"\s+CGPA\s*:.*$",
        "",
        title_line,
        flags=re.IGNORECASE,
    ).strip()

    return [
        {
            "raw_header": title_line,
            "title": title,
            "organization": organization,
            "dates": dates,
            "bullets": [],
            "cgpa": cgpa,
        }
    ]


def _parse_projects(
    block_lines: list[str],
) -> list[dict]:
    """
    Parse the two project blocks.

    A project starts with a line containing '|'.

    Example:

    Smart Delivery Operations Analytics | SQL, MySQL, Power BI

    followed by description and bullet lines.
    """

    projects = []

    current = None

    for raw_line in block_lines:

        line = _clean_line(raw_line)

        if not line:
            continue

        # Project title contains '|'.
        if "|" in line:

            if current:
                projects.append(current)

            name, technologies = line.split("|", 1)

            current = {
                "name": name.strip(),
                "technologies": technologies.strip(),
                "description": None,
                "bullets": [],
            }

            continue

        # If there is no project yet, skip stray text.
        if current is None:
            continue

        # Bullet point.
        if _is_bullet(line):

            bullet = _remove_bullet(line)

            if bullet:
                current["bullets"].append(bullet)

        # Project description line.
        elif current["description"] is None:

            current["description"] = line

        else:

            # Continuation of previous description/bullet.
            if current["bullets"]:
                current["bullets"][-1] += " " + line
            else:
                current["description"] += " " + line

    if current:
        projects.append(current)

    return projects


def _parse_experience(
    block_lines: list[str],
) -> list[dict]:
    """
    Generic experience parser.

    This resume currently has no experience section,
    so this safely returns an empty list when absent.
    """

    entries = []

    current = None

    for raw_line in block_lines:

        line = _clean_line(raw_line)

        if not line:
            continue

        if _is_bullet(line):

            if current is None:
                current = {
                    "title": "",
                    "organization": None,
                    "dates": None,
                    "bullets": [],
                }
                entries.append(current)

            current["bullets"].append(
                _remove_bullet(line)
            )

        else:

            if current:
                entries.append(current)

            current = {
                "title": line,
                "organization": None,
                "dates": None,
                "bullets": [],
            }

    if current and current not in entries:
        entries.append(current)

    return entries


def parse_master_resume(
    raw_text: str,
) -> dict:
    """
    Parse the master resume into structured JSON.
    """

    lines = raw_text.splitlines()

    sections = _find_sections(lines)

    contact = _extract_contact(
        raw_text,
        lines,
    )

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------

    summary_lines = sections.get(
        "summary",
        [],
    )

    summary = " ".join(
        _clean_line(line)
        for line in summary_lines
        if _clean_line(line)
    )

    # ---------------------------------------------------------------
    # Skills
    # ---------------------------------------------------------------

    skills = _parse_skills(
        sections.get("skills", [])
    )

    # ---------------------------------------------------------------
    # Education
    # ---------------------------------------------------------------

    education = _parse_education(
        sections.get("education", [])
    )

    # ---------------------------------------------------------------
    # Projects
    # ---------------------------------------------------------------

    projects = _parse_projects(
        sections.get("projects", [])
    )

    # ---------------------------------------------------------------
    # Experience
    # ---------------------------------------------------------------

    experience = _parse_experience(
        sections.get("experience", [])
    )

    # ---------------------------------------------------------------
    # Soft Skills
    # ---------------------------------------------------------------

    soft_skills = _parse_simple_list(
        sections.get("soft_skills", [])
    )

    # ---------------------------------------------------------------
    # Certifications
    # ---------------------------------------------------------------

    certifications = _parse_simple_list(
        sections.get("certifications", [])
    )

    # ---------------------------------------------------------------
    # Achievements
    # ---------------------------------------------------------------

    achievements = _parse_simple_list(
        sections.get("achievements", [])
    )

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