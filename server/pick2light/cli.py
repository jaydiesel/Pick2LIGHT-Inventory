import json

import typer
import uvicorn

from pick2light.config import Settings, get_settings
from pick2light.db import upgrade_database

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
