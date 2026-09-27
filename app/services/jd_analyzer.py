"""
Compares a job description against a candidate's parsed master resume to
produce: an overall relevance score (0-100), the skills that overlap, and
the skills the JD asks for that the resume doesn't mention (a real gap list,
not a suggestion to fabricate experience).

Method: TF-IDF cosine similarity over the full text (captures general topical
overlap) blended with an exact skill-taxonomy overlap ratio (captures the
concrete "do they have skill X" signal recruiters/ATS systems actually
filter on). No external model download required.
"""
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.services.skills_data import ALL_SKILLS

_SKILL_PATTERNS = {skill: re.compile(rf"(?<!\w){re.escape(skill)}(?!\w)", re.IGNORECASE) for skill in ALL_SKILLS}


def extract_skills_from_text(text: str) -> list[str]:
    found = []
    for skill, pattern in _SKILL_PATTERNS.items():
        if pattern.search(text):
            found.append(skill)
    return found


def _text_similarity(resume_text: str, jd_text: str) -> float:
    if not resume_text.strip() or not jd_text.strip():
        return 0.0
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform([resume_text, jd_text])
    except ValueError:
        # e.g. both documents are pure stop-words / empty after vectorization
        return 0.0
    return float(cosine_similarity(matrix[0], matrix[1])[0][0])


def analyze_job_match(resume_raw_text: str, resume_skills: list[str], jd_text: str) -> dict:
    """
    resume_skills: skills already recorded on the master resume (from parsing
    or manual edits) -- used in addition to whatever extract_skills_from_text
    finds in the raw resume text, in case the parser missed some.
    """
    jd_skills = set(extract_skills_from_text(jd_text))
    resume_skill_set = set(s.strip() for s in resume_skills if s.strip()) | set(
        extract_skills_from_text(resume_raw_text)
    )

    # normalize case for comparison but keep original casing for display
    resume_skill_lower = {s.lower() for s in resume_skill_set}
    matched_skills = sorted([s for s in jd_skills if s.lower() in resume_skill_lower])
    missing_skills = sorted([s for s in jd_skills if s.lower() not in resume_skill_lower])

    skill_overlap_ratio = (len(matched_skills) / len(jd_skills)) if jd_skills else 0.0
    topical_similarity = _text_similarity(resume_raw_text, jd_text)

    # Blend: skill overlap is the stronger, more concrete signal.
    blended = (0.65 * skill_overlap_ratio) + (0.35 * topical_similarity)
    relevance_score = round(min(blended, 1.0) * 100, 1)

    return {
        "relevance_score": relevance_score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "topical_similarity": round(topical_similarity * 100, 1),
        "skill_overlap_ratio": round(skill_overlap_ratio * 100, 1),
    }
