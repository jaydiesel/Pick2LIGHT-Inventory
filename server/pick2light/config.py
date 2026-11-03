import secrets
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="P2L_", extra="ignore")

    database_url: str = "postgresql+asyncpg://p2l:p2l@localhost:5432/pick2light"
    data_dir: Path = Path("./data")
    backup_dir: Path | None = None  # defaults to data_dir/"backups"
    # If unset, generated once and persisted to data_dir/secret_key.
    secret_key: str = ""
    web_dist: Path | None = None
    host: str = "0.0.0.0"  # container deployment; reachable on the LAN by design
    port: int = 80
    auto_migrate: bool = True
    allow_reset: bool = False

    @model_validator(mode="after")
    def _fill_derived(self) -> Self:
        if self.backup_dir is None:
            self.backup_dir = self.data_dir / "backups"
        if not self.secret_key:
            self.secret_key = _load_or_create_secret(self.data_dir / "secret_key")
        return self


def _load_or_create_secret(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    try:
        # Exclusive create so concurrent starters cannot overwrite each other's key.
        with path.open("x") as f:
            path.chmod(0o600)
            f.write(key)
    except FileExistsError:
        return path.read_text().strip()
    return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
