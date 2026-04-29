from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: str
    db_ssl_ca: str = "./global-bundle.pem"
    gemini_api_key: str = ""

    # GitHub integration (read-only access to IDRE codebase)
    github_token: str = ""
    github_repo_owner: str = "OrchidSoftwareSolutions"
    github_repo_name: str = "idre"

    # Confluence integration (read-only access to documentation)
    confluence_url: str = ""
    confluence_username: str = ""
    confluence_api_token: str = ""
    confluence_space_keys: str = "SD,IDRE,ADS"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "case_sensitive": False,
    }

    @property
    def confluence_spaces(self) -> list[str]:
        return [s.strip() for s in self.confluence_space_keys.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
