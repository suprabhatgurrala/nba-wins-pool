"""A counter that moves whenever this process commits a database write, so cached results can tell they're stale."""

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

_WROTE = "data_version_wrote"
_version = 0


def db_version() -> int:
    return _version


def bump_db_version() -> None:
    """Mark every cached result stale, e.g. after another process wrote to the database."""
    global _version
    _version += 1


@event.listens_for(Session, "after_flush")
def _flushed(session: Session, _flush_context) -> None:
    session.info[_WROTE] = True


@event.listens_for(Session, "do_orm_execute")
def _executed(state: ORMExecuteState) -> None:
    if not state.is_select:
        state.session.info[_WROTE] = True


@event.listens_for(Session, "after_commit")
def _committed(session: Session) -> None:
    if session.info.pop(_WROTE, False):
        bump_db_version()


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: Session) -> None:
    session.info.pop(_WROTE, None)
