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


@app.command()
def backup() -> None:
    """Create a backup now (database + attachments)."""
    import asyncio

    from pick2light.backup.service import create_backup
    from pick2light.config import get_settings

    info = asyncio.run(create_backup(get_settings()))
    typer.echo(f"Backup written: {info.name}")


@app.command()
def restore(
    file: Path, yes: bool = typer.Option(False, "--yes", help="Confirm replacing all current data")
) -> None:
    """Restore a backup file, replacing the current database and attachments."""
    import asyncio
    from types import SimpleNamespace

    from pick2light.backup.service import restore_backup
    from pick2light.config import get_settings

    if not yes:
        typer.echo("Restoring replaces ALL current data. Re-run with --yes to confirm.", err=True)
        raise typer.Exit(1)
    asyncio.run(restore_backup(get_settings(), file, SimpleNamespace(maintenance=False)))
    typer.echo(f"Restored {file.name}")


@app.command("backup-scheduler")
def backup_scheduler() -> None:
    """Run nightly backups on the schedule set in Settings (used by the Docker backup service)."""
    import asyncio

    from pick2light.backup.service import scheduler_loop
    from pick2light.config import get_settings

    asyncio.run(scheduler_loop(get_settings(), asyncio.Event()))


@app.command("reset-db")
def reset_db(yes: bool = typer.Option(False, "--yes")) -> None:
    """Drop and recreate the database schema (development and tests only)."""
    import asyncio

    import asyncpg

    from pick2light.backup.service import libpq_url
    from pick2light.config import get_settings

    settings = get_settings()
    if not settings.allow_reset:
        typer.echo("Refusing to reset: set P2L_ALLOW_RESET=1 to allow it.", err=True)
        raise typer.Exit(1)
    if not yes:
        typer.echo("This deletes ALL data. Re-run with --yes to confirm.", err=True)
        raise typer.Exit(1)

    async def _reset() -> None:
        conn = await asyncpg.connect(libpq_url(settings.database_url))
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        finally:
            await conn.close()

    asyncio.run(_reset())
    run_migrations(settings.database_url)
    typer.echo("Database reset.")


def main() -> None:
    app()
