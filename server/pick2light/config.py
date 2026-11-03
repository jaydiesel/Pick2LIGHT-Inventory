import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="P2L_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://p2l:p2l@localhost:5432/pick2light"
    data_dir: Path = Path("./data")
    backup_dir: Path | None = None
    secret_key: str = ""
    web_dist: Path | None = None
    host: str = "0.0.0.0"
    port: int = 80
    auto_migrate: bool = True
    allow_reset: bool = False

    @model_validator(mode="after")
    def _defaults(self) -> "Settings":
        if self.backup_dir is None:
            self.backup_dir = self.data_dir / "backups"
        return self

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    def resolved_secret_key(self) -> str:
        """Return the configured secret, generating and persisting one on first use."""
        if self.secret_key:
            return self.secret_key
        path = self.data_dir / "secret_key"
        if path.exists():
            self.secret_key = path.read_text().strip()
        else:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.secret_key = secrets.token_urlsafe(48)
            path.write_text(self.secret_key)
            path.chmod(0o600)
        return self.secret_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
