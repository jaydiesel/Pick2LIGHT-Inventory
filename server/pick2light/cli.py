import json
from pathlib import Path

import typer

app = typer.Typer(help="Pick2LIGHT-Inventory server", no_args_is_help=True)
SERVER_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(url: str | None = None):
    from alembic.config import Config

    cfg = Config(str(SERVER_DIR / "alembic.ini")) if (SERVER_DIR / "alembic.ini").exists() else Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def run_migrations(url: str) -> None:
    from alembic import command

    command.upgrade(_alembic_config(url), "head")


@app.command()
def migrate() -> None:
    """Apply database migrations."""
    from pick2light.config import get_settings

    run_migrations(get_settings().database_url)
    typer.echo("Database is up to date.")


@app.command()
def serve(host: str | None = None, port: int | None = None) -> None:
    """Run the web server (applies migrations first when P2L_AUTO_MIGRATE is true)."""
    import uvicorn

    from pick2light.app import create_app
    from pick2light.config import get_settings

    settings = get_settings()
    if settings.auto_migrate:
        run_migrations(settings.database_url)
    uvicorn.run(create_app(settings), host=host or settings.host, port=port or settings.port)


@app.command()
def openapi() -> None:
    """Print the OpenAPI schema as JSON."""
    from pick2light.app import create_app

    typer.echo(json.dumps(create_app().openapi(), indent=2))


def main() -> None:
    app()
