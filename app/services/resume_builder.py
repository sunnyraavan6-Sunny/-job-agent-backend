"""
Turns (parsed master resume + job-match analysis) into a tailored, compiled
PDF resume.

Important constraint this module honors: it never invents skills, employers,
titles, or bullet points. All it does with the "tailoring" is:
  1. Reorder the skills list so JD-relevant skills appear first.
  2. Reorder each job's existing bullet points so the ones mentioning
     JD-relevant keywords surface first.
  3. Escape everything for safe LaTeX rendering, then compile to PDF.
No new facts are ever generated.
"""
import re
import subprocess
from pathlib import Path

import jinja2

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_resumes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_SPECIAL_CHARS))


def _escape_latex(value):
    """Recursively escape strings inside str/list/dict structures for LaTeX safety."""
    if value is None:
        return None
    if isinstance(value, str):
        return _ESCAPE_RE.sub(lambda m: _LATEX_SPECIAL_CHARS[m.group(0)], value)
    if isinstance(value, list):
        return [_escape_latex(v) for v in value]
    if isinstance(value, dict):
        return {k: _escape_latex(v) for k, v in value.items()}
    return value


def _keyword_score(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def tailor_resume_content(parsed_resume: dict, matched_skills: list[str]) -> dict:
    """
    Produces a tailored *copy* of parsed_resume: same facts, reordered for
    relevance. Does not mutate the input.
    """
    tailored = {
        "contact": parsed_resume.get("contact", {}),
        "summary": parsed_resume.get("summary", ""),
        "certifications": parsed_resume.get("certifications", []),
    }

    all_skills = list(parsed_resume.get("skills", []))
    matched_lower = {s.lower() for s in matched_skills}
    original_order = {skill: idx for idx, skill in enumerate(all_skills)}
    all_skills = sorted(all_skills, key=lambda s: (s.lower() not in matched_lower, original_order[s]))
    tailored["skills"] = all_skills

    def reorder_bullets(entries: list[dict]) -> list[dict]:
        result = []
        for entry in entries:
            bullets = list(entry.get("bullets", []))
            bullets.sort(key=lambda b: -_keyword_score(b, matched_skills))
            result.append({**entry, "bullets": bullets})
        return result

    tailored["experience"] = reorder_bullets(parsed_resume.get("experience", []))
    tailored["projects"] = reorder_bullets(parsed_resume.get("projects", []))
    tailored["education"] = parsed_resume.get("education", [])

    return tailored


def render_latex(tailored_resume: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )
    template = env.get_template("resume_template.tex.jinja")
    escaped = _escape_latex(tailored_resume)
    return template.render(**escaped)


def compile_latex_to_pdf(tex_content: str, output_basename: str) -> tuple[str | None, str]:
    """
    Compiles tex_content to a PDF using pdflatex if available.
    Returns (pdf_path_or_None, log_message).
    """
    work_dir = OUTPUT_DIR / output_basename
    work_dir.mkdir(parents=True, exist_ok=True)
    tex_path = work_dir / f"{output_basename}.tex"
    tex_path.write_text(tex_content, encoding="utf-8")

    try:
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{output_basename}.tex"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return None, "pdflatex is not installed in this environment; .tex file was saved but not compiled."
    except subprocess.TimeoutExpired:
        return None, "LaTeX compilation timed out."

    pdf_path = work_dir / f"{output_basename}.pdf"
    if result.returncode == 0 and pdf_path.exists():
        return str(pdf_path), "Compiled successfully."

    return None, f"LaTeX compilation failed (exit {result.returncode}). See {work_dir}/{output_basename}.log"


def build_tailored_resume(parsed_resume: dict, matched_skills: list[str], output_basename: str) -> dict:
    tailored = tailor_resume_content(parsed_resume, matched_skills)
    tex_content = render_latex(tailored)
    pdf_path, log_message = compile_latex_to_pdf(tex_content, output_basename)
    return {
        "tex_content": tex_content,
        "pdf_path": pdf_path,
        "log_message": log_message,
        "emphasis_notes": {
            "skills_prioritized": [s for s in tailored["skills"] if s.lower() in {m.lower() for m in matched_skills}],
        },
    }
