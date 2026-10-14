"""Flask CLI helpers:  flask --app run <command>"""
import click

from .extensions import db
from .services.csv_parser import CSVParseError, parse_bank_csv


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all tables (quick start; use `flask db upgrade` for migrations)."""
        db.create_all()
        click.echo("Tables created.")

    @app.cli.command("parse-csv")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--dayfirst/--monthfirst", default=None, help="Prefer DD/MM or MM/DD when dates are ambiguous.")
    @click.option("--invert-sign", is_flag=True, help="Treat positive amounts as expenses (credit-card exports).")
    def parse_csv(path, dayfirst, invert_sign):
        """Preview how a bank CSV will be parsed (no database access)."""
        with open(path, "rb") as fh:
            try:
                result = parse_bank_csv(fh, dayfirst=dayfirst, invert_sign=invert_sign)
            except CSVParseError as exc:
                raise click.ClickException(str(exc))
        click.echo(f"columns:     {result.columns}")
        click.echo(f"delimiter:   {result.delimiter!r}   encoding: {result.encoding}   date format: {result.date_format}")
        click.echo(f"summary:     {result.summary()}")
        for w in result.warnings:
            click.echo(f"WARNING: {w}")
        click.echo(result.transactions.head(15).to_string(index=False))
        for e in result.errors[:20]:
            click.echo(f"rejected row {e.row}: {e.reason}  [{e.raw}]")
