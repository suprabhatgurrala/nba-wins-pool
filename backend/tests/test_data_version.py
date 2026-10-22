from typing import Optional

from sqlalchemy import create_engine, text
from sqlmodel import Field, Session, SQLModel, select

from nba_wins_pool.utils.data_version import db_version


class VersionedThing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str


def _session() -> Session:
    engine = create_engine("sqlite://")
    VersionedThing.metadata.create_all(engine, tables=[VersionedThing.__table__])
    return Session(engine)


def test_committing_a_write_moves_the_version():
    with _session() as session:
        before = db_version()
        session.add(VersionedThing(name="a"))
        session.commit()

        assert db_version() == before + 1


def test_reads_and_rolled_back_writes_leave_the_version_alone():
    with _session() as session:
        before = db_version()
        session.exec(select(VersionedThing)).all()
        session.commit()
        session.add(VersionedThing(name="a"))
        session.flush()
        session.rollback()
        session.commit()

        assert db_version() == before


def test_raw_statements_count_as_writes():
    with _session() as session:
        before = db_version()
        session.execute(text("INSERT INTO versionedthing (name) VALUES ('b')"))
        session.commit()

        assert db_version() == before + 1
