import asyncio
import json
import signal
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from pick2light.backup.service import create_backup, restore_backup, scheduler_loop
from pick2light.config import Settings, get_settings
from pick2light.db import upgrade_database
from pick2light.errors import AppError

app = typer.Typer(help="Pick2LIGHT-Inventory server", no_args_is_help=True)


@app.command()
def migrate() -> None:
    """Apply database migrations."""
    upgrade_database(get_settings().database_url)


@app.command()
def serve() -> None:
    """Run the server (applying migrations first when auto_migrate is on)."""
    settings = get_settings()
    if settings.auto_migrate:
        upgrade_database(settings.database_url)
    uvicorn.run("pick2light.app:create_app", factory=True, host=settings.host, port=settings.port)


@app.command()
def openapi() -> None:
    """Print the OpenAPI schema as JSON."""
    from pick2light.app import create_app

    typer.echo(json.dumps(create_app(Settings(secret_key="openapi")).openapi(), indent=2))


def _reset_schema(database_url: str) -> None:
    async def run() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    asyncio.run(run())
    upgrade_database(database_url)


@app.command()
def backup() -> None:
    """Create a backup now."""
    info = asyncio.run(create_backup(get_settings()))
    typer.echo(f"Backup written: {info.name}")


@app.command()
def restore(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    yes: Annotated[bool, typer.Option("--yes", help="Confirm replacing all data.")] = False,
) -> None:
    """Restore the database and attachments from a backup file."""
    if not yes:
        typer.echo("Restoring replaces ALL current data. Re-run with --yes to confirm.", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(restore_backup(get_settings(), file, SimpleNamespace(maintenance=False)))
    except AppError as exc:
        typer.echo(f"Restore failed: {exc.message}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("Restore complete.")


@app.command("backup-scheduler")
def backup_scheduler() -> None:
    """Run the nightly backup job in the foreground."""

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await scheduler_loop(get_settings(), stop)

    asyncio.run(run())


@app.command("reset-db")
def reset_db(
    yes: Annotated[bool, typer.Option("--yes", help="Confirm deleting all data.")] = False,
) -> None:
    """Drop all data and recreate an empty schema (development only)."""
    settings = get_settings()
    if not settings.allow_reset:
        typer.echo("reset-db is disabled: set P2L_ALLOW_RESET=1 to allow it.", err=True)
        raise typer.Exit(1)
    if not yes:
        typer.echo("This deletes ALL data. Re-run with --yes to confirm.", err=True)
        raise typer.Exit(1)
    _reset_schema(settings.database_url)
    typer.echo("Database reset.")
