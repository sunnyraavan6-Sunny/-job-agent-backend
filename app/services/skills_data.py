"""
A curated, deliberately broad skills taxonomy for keyword/skill matching
between a resume and a job description. This is intentionally simple
(exact/word-boundary matching against a known list) rather than a trained
NER model, so it has zero external model-download dependency and is fully
auditable/extendable -- add to these lists as needed for your field.
"""

TECH_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust", "Ruby", "PHP",
    "Kotlin", "Swift", "Scala", "R", "MATLAB", "Perl", "SQL", "NoSQL", "HTML", "CSS",
    "FastAPI", "Django", "Flask", "Spring", "Spring Boot", "Express.js", "Node.js", "React",
    "Angular", "Vue.js", "Next.js", "GraphQL", "REST", "gRPC", "Microservices",
    "MySQL", "PostgreSQL", "MongoDB", "Redis", "Elasticsearch", "SQLite", "Cassandra",
    "DynamoDB", "Oracle", "MariaDB", "Snowflake", "BigQuery", "Redshift",
    "AWS", "Azure", "GCP", "Google Cloud", "Docker", "Kubernetes", "Terraform", "Ansible",
    "Jenkins", "CI/CD", "GitHub Actions", "GitLab CI", "Helm", "Prometheus", "Grafana",
    "Linux", "Bash", "Shell Scripting", "Nginx", "Apache",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "TensorFlow", "PyTorch",
    "Scikit-learn", "Pandas", "NumPy", "Data Analysis", "Data Engineering", "Data Science",
    "ETL", "Airflow", "Spark", "Hadoop", "Kafka", "Tableau", "Power BI", "Looker",
    "Git", "GitHub", "GitLab", "Bitbucket", "Jira", "Confluence", "Agile", "Scrum", "Kanban",
    "Unit Testing", "Integration Testing", "TDD", "Selenium", "Pytest", "JUnit",
    "System Design", "OOP", "Design Patterns", "Data Structures", "Algorithms",
    "Android", "iOS", "React Native", "Flutter",
    "Cybersecurity", "Penetration Testing", "OAuth", "JWT", "Encryption",
    "Salesforce", "SAP", "Excel", "VBA", "Power Automate",
]

SOFT_SKILLS = [
    "Leadership", "Communication", "Teamwork", "Problem Solving", "Critical Thinking",
    "Project Management", "Stakeholder Management", "Mentoring", "Cross-functional Collaboration",
    "Time Management", "Adaptability", "Negotiation", "Presentation Skills",
]

ALL_SKILLS = sorted(set(TECH_SKILLS + SOFT_SKILLS), key=str.lower)
