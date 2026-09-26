import json
import sys

sys.path.insert(0, ".")

from app.services.jd_analyzer import analyze_job_match
from app.services.resume_builder import build_tailored_resume
from app.services.resume_parser import parse_master_resume

SAMPLE_RESUME = """Jordan Lee
jordan.lee@example.com | +1 555-123-4567 | linkedin.com/in/jordanlee | github.com/jordanlee

SUMMARY
Backend engineer with 5 years of experience building scalable APIs and data pipelines.

SKILLS
Python, FastAPI, Django, PostgreSQL, MySQL, Docker, Kubernetes, AWS, Redis, Kafka, Git, CI/CD

EXPERIENCE
Backend Engineer, Acme Corp | Jan 2022 - Present
- Built and maintained REST APIs serving 2M+ requests/day using FastAPI and PostgreSQL
- Migrated legacy monolith to microservices architecture on Kubernetes, cutting deploy time by 60%
- Mentored 2 junior engineers and led code review practices for the backend team

Software Engineer, Beta Inc | Jun 2019 - Dec 2021
- Developed data ingestion pipelines processing 500GB/day using Kafka and Spark
- Implemented caching layer with Redis, reducing average API latency by 40%

PROJECTS
Personal Finance Tracker
- Built a full-stack app with React and Django REST framework for expense tracking
- Deployed on AWS using Docker and GitHub Actions for CI/CD

EDUCATION
B.S. in Computer Science, State University | 2015 - 2019

CERTIFICATIONS
AWS Certified Solutions Architect - Associate
"""

SAMPLE_JD = """
We are looking for a Backend Engineer with strong Python and FastAPI experience
to join our platform team. You will design and build REST APIs, work with
PostgreSQL and Redis, and deploy services on Kubernetes and AWS. Experience with
Kafka for event streaming and CI/CD pipelines is a strong plus. You should be
comfortable mentoring junior engineers and collaborating cross-functionally.
"""

print("== parsing master resume ==")
parsed = parse_master_resume(SAMPLE_RESUME)
print(json.dumps(parsed, indent=2))

print("\n== analyzing JD match ==")
analysis = analyze_job_match(SAMPLE_RESUME, parsed["skills"], SAMPLE_JD)
print(json.dumps(analysis, indent=2))

assert analysis["relevance_score"] > 50, "expected a strong match for this synthetic example"
assert "Python" in analysis["matched_skills"]
assert "FastAPI" in analysis["matched_skills"]

print("\n== building tailored resume ==")
result = build_tailored_resume(parsed, analysis["matched_skills"], output_basename="test_resume")
print("log:", result["log_message"])
print("pdf_path:", result["pdf_path"])
print("emphasis_notes:", result["emphasis_notes"])

assert result["pdf_path"] is not None, f"PDF compilation failed: {result['log_message']}"
import os
assert os.path.exists(result["pdf_path"])
print(f"\nPDF size: {os.path.getsize(result['pdf_path'])} bytes")

print("\nALL SERVICE-LAYER CHECKS PASSED")
