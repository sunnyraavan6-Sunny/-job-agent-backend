from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "job_agent"
    mysql_password: str = "job_agent"
    mysql_database: str = "job_agent"

    secret_key: str = "insecure-dev-key-change-me"
    access_token_expire_minutes: int = 1440
    algorithm: str = "HS256"
    environment: str = "development"

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "us"

    # Outreach: SMTP for sending cold emails
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from_email: str = ""
    smtp_from_name: str = "Job Search Agent"

    # Outreach: optional LLM-assisted email drafting (falls back to templates if unset)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"  # verify current model names at docs.claude.com before relying on this

    follow_up_after_days: int = 7

    cors_origins: str = "*"  # comma-separated list in production, e.g. "https://your-frontend.up.railway.app"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )


settings = Settings()
