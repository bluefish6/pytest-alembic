import functools
import itertools
from dataclasses import dataclass
from io import StringIO
from typing import Dict, List, Union

import alembic
from alembic.config import Config
from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Connection


@dataclass
class CommandExecutor:
    alembic_config: Config
    stdout: StringIO
    stream_position: int

    @classmethod
    def from_config(cls, config):
        file = config.get("file", "alembic.ini")
        script_location = config.get("script_location", "migrations")
        target_metadata = config.get("target_metadata")
        process_revision_directives = config.get("process_revision_directives")
        include_schemas = config.get("include_schemas", True)

        stdout = StringIO()
        alembic_config = Config(file, stdout=stdout)
        alembic_config.set_main_option("script_location", script_location)

        alembic_config.attributes["target_metadata"] = target_metadata
        alembic_config.attributes["process_revi"] = process_revision_directives
        alembic_config.attributes["include_schemas"] = include_schemas

        return cls(alembic_config=alembic_config, stdout=stdout, stream_position=0)

    def configure(self, **kwargs):
        for key, value in kwargs.items():
            self.alembic_config.attributes[key] = value

    @property
    def connection(self):
        return self.alembic_config.attributes["connection"]

    def run_command(self, command, *args, **kwargs):
        self.stream_position = self.stdout.tell()

        executable_command = getattr(alembic.command, command)
        try:
            executable_command(self.alembic_config, *args, **kwargs)
        except alembic.util.exc.CommandError as e:
            raise RuntimeError(e)

        self.stdout.seek(self.stream_position)
        return self.stdout.readlines()


@dataclass
class ConnectionExecutor:
    connection: Connection

    @classmethod
    @functools.lru_cache()
    def metadata(cls, revision: str) -> MetaData:
        return MetaData()

    @classmethod
    @functools.lru_cache()
    def table(cls, revision: str, name: str, connection: Connection) -> Table:
        meta = cls.metadata(revision)
        return Table(name, meta, autoload=True, autoload_with=connection)

    def table_insert(self, revision: str, data: Union[Dict, List], tablename=None):
        if isinstance(data, dict):
            data = [data]

        def by_tablename(item):
            _tablename = item.get("__tablename__")
            return _tablename or tablename

        def filter_non_column(item):
            return {k: v for k, v in item.items() if k != "__tablename__"}

        grouped_data = itertools.groupby(sorted(data, key=by_tablename), key=by_tablename)
        per_table_data = {t: [filter_non_column(item) for item in data] for t, data in grouped_data}

        for tablename, data in per_table_data.items():
            table = self.table(revision, tablename, self.connection)
            self.connection.execute(table.insert().values(data))
