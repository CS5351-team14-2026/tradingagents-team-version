"""LangGraph checkpoint support for resumable analysis runs.

Per-ticker SQLite databases so concurrent tickers don't contend.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from tradingagents.dataflows.symbols import safe_ticker_component
from tradingagents.run_budget import BudgetLedgerError, RunBudgetTracker


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    """Return the SQLite checkpoint DB path for a ticker."""
    # Reject ticker values that would escape the checkpoints directory.
    safe = safe_ticker_component(ticker).upper()
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe}.db"


class BudgetLedgerStore:
    """Durable cumulative usage, independent of graph checkpoint commits.

    Implements REQ-TA-FR-002 D8/ADR-003. Only the tracker's validated accounting
    allowlist is stored, in a separate table in the existing per-ticker SQLite
    database. Each update commits a complete per-call ledger atomically; call
    IDs retain idempotence across duplicate callbacks and graph replays.

    A store reads one revision and uses compare-and-swap on every write. Two
    resumed workers cannot silently overwrite each other's usage. Clearing a
    store retires that writer, so a late callback cannot resurrect a completed
    run or overwrite another run's row. It never deletes graph checkpoints.
    """

    def __init__(self, data_dir: str | Path, ticker: str, thread_id: str):
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("budget ledger thread_id must be a non-empty string")
        try:
            self._db = _db_path(data_dir, ticker)
        except OSError:
            raise BudgetLedgerError("BUDGET_LEDGER_WRITE_FAILED") from None
        self._thread_id = thread_id
        self._lock = RLock()
        self._loaded = False
        self._closed = False
        self._revision: int | None = None
        self._run_id: str | None = None
        self._generation: str | None = None

    def _connect(self):
        conn = sqlite3.connect(str(self._db))
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS budget_ledgers (
                thread_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                generation TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                state_json TEXT NOT NULL
            )""")
            conn.commit()
        except BaseException:
            conn.close()
            raise
        return conn

    @staticmethod
    def _validated(state: Any) -> dict[str, Any]:
        try:
            return RunBudgetTracker.restore(state).export_state()
        except (TypeError, ValueError):
            raise BudgetLedgerError("BUDGET_LEDGER_INVALID") from None

    def load(self) -> dict[str, Any] | None:
        """Read and validate the ledger; missing history is distinct from empty.

        No malformed data is silently discarded. A fresh store may load a
        missing row and then bind a new tracker; a cleared writer stays retired.
        """
        with self._lock:
            if self._closed:
                return None
            if not self._db.exists():
                self._loaded, self._revision, self._run_id, self._generation = True, None, None, None
                return None
            conn = None
            try:
                conn = self._connect()
                row = conn.execute(
                    "SELECT run_id, revision, generation, state_json FROM budget_ledgers WHERE thread_id = ?",
                    (self._thread_id,),
                ).fetchone()
                if row is None:
                    self._loaded, self._revision, self._run_id, self._generation = True, None, None, None
                    return None
                try:
                    state = self._validated(json.loads(row[3]))
                except (TypeError, ValueError):
                    raise BudgetLedgerError("BUDGET_LEDGER_INVALID") from None
                if (state["run_id"] != row[0] or type(row[1]) is not int or row[1] < 1
                        or not isinstance(row[2], str) or not row[2]):
                    raise BudgetLedgerError("BUDGET_LEDGER_INVALID")
                self._loaded, self._revision, self._run_id, self._generation = True, row[1], row[0], row[2]
                return state
            except sqlite3.Error:
                raise BudgetLedgerError("BUDGET_LEDGER_READ_FAILED") from None
            finally:
                if conn is not None:
                    conn.close()

    def save_state(self, state: dict[str, Any]) -> None:
        """Commit allowlisted state or raise, never returning after a stale write."""
        with self._lock:
            if self._closed:
                raise BudgetLedgerError("BUDGET_LEDGER_CLOSED")
            validated = self._validated(state)
            if not self._loaded and self.load() is not None:
                # Existing state must be explicitly loaded/restored, not
                # replaced by an accidentally fresh zero-initialized tracker.
                raise BudgetLedgerError("BUDGET_LEDGER_ALREADY_EXISTS")
            if self._run_id is not None and validated["run_id"] != self._run_id:
                raise BudgetLedgerError("BUDGET_LEDGER_IDENTITY_MISMATCH")
            encoded = json.dumps(validated, sort_keys=True, separators=(",", ":"), allow_nan=False)
            conn = None
            try:
                conn = self._connect()
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT run_id, revision, generation FROM budget_ledgers WHERE thread_id = ?",
                        (self._thread_id,),
                    ).fetchone()
                    if self._revision is None:
                        if row is not None:
                            raise BudgetLedgerError("BUDGET_LEDGER_CONFLICT")
                        revision = 1
                        generation = str(uuid4())
                        conn.execute(
                            "INSERT INTO budget_ledgers (thread_id, run_id, revision, generation, state_json) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (self._thread_id, validated["run_id"], revision, generation, encoded),
                        )
                    else:
                        if row != (self._run_id, self._revision, self._generation):
                            raise BudgetLedgerError("BUDGET_LEDGER_CONFLICT")
                        revision = self._revision + 1
                        generation = self._generation
                        changed = conn.execute(
                            "UPDATE budget_ledgers SET revision = ?, state_json = ? "
                            "WHERE thread_id = ? AND run_id = ? AND revision = ? AND generation = ?",
                            (revision, encoded, self._thread_id, self._run_id, self._revision, generation),
                        )
                        if changed.rowcount != 1:
                            raise BudgetLedgerError("BUDGET_LEDGER_CONFLICT")
                self._revision, self._run_id, self._generation = revision, validated["run_id"], generation
            except sqlite3.Error:
                raise BudgetLedgerError("BUDGET_LEDGER_WRITE_FAILED") from None
            finally:
                if conn is not None:
                    conn.close()

    def clear(self) -> None:
        """Delete only this revision and permanently retire this writer."""
        with self._lock:
            if self._closed:
                return
            if not self._loaded:
                self.load()
            conn = None
            try:
                conn = self._connect()
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT run_id, revision, generation FROM budget_ledgers WHERE thread_id = ?",
                        (self._thread_id,),
                    ).fetchone()
                    if row is not None:
                        if row != (self._run_id, self._revision, self._generation):
                            raise BudgetLedgerError("BUDGET_LEDGER_CONFLICT")
                        conn.execute(
                            "DELETE FROM budget_ledgers WHERE thread_id = ? AND run_id = ? AND revision = ? "
                            "AND generation = ?",
                            (self._thread_id, self._run_id, self._revision, self._generation),
                        )
                    elif self._revision is not None:
                        raise BudgetLedgerError("BUDGET_LEDGER_CONFLICT")
                self._closed = True
            except sqlite3.Error:
                raise BudgetLedgerError("BUDGET_LEDGER_CLEAR_FAILED") from None
            finally:
                if conn is not None:
                    conn.close()


def thread_id(ticker: str, date: str, signature: str = "") -> str:
    """Deterministic thread ID for a ticker+date pair.

    ``signature`` folds in graph-shape-affecting run choices so a resume under a
    different graph can't reuse this checkpoint (#1089); omitting it keeps the
    legacy ID.
    """
    base = f"{ticker.upper()}:{date}"
    if signature:
        base = f"{base}:{signature}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


@contextmanager
def get_checkpointer(data_dir: str | Path, ticker: str) -> Generator[SqliteSaver, None, None]:
    """Context manager yielding a SqliteSaver backed by a per-ticker DB."""
    db = _db_path(data_dir, ticker)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        saver.setup()
        yield saver
    finally:
        conn.close()


def checkpoint_step(data_dir: str | Path, ticker: str, date: str, signature: str = "") -> int | None:
    """Return the step number of the latest checkpoint, or None if none exists."""
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return None
    tid = thread_id(ticker, date, signature)
    with get_checkpointer(data_dir, ticker) as saver:
        config = {"configurable": {"thread_id": tid}}
        cp = saver.get_tuple(config)
        if cp is None:
            return None
        return cp.metadata.get("step")


def clear_all_checkpoints(data_dir: str | Path) -> int:
    """Remove all checkpoint databases. Returns the number of databases deleted.

    SQLite keeps committed state in ``-wal`` and ``-shm`` files beside the
    database, so deleting only the ``.db`` leaves a cleared checkpoint with data
    still on disk.
    """
    cp_dir = Path(data_dir) / "checkpoints"
    if not cp_dir.exists():
        return 0
    dbs = list(cp_dir.glob("*.db"))
    for db in dbs:
        for path in (db, *cp_dir.glob(f"{db.name}-*")):
            path.unlink(missing_ok=True)
    return len(dbs)


def clear_checkpoint(data_dir: str | Path, ticker: str, date: str, signature: str = "") -> None:
    """Remove checkpoint for a specific ticker+date by deleting the thread's rows."""
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return
    tid = thread_id(ticker, date, signature)
    conn = sqlite3.connect(str(db))
    try:
        for table in ("writes", "checkpoints"):
            conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='budget_ledgers'").fetchone():
            conn.execute("DELETE FROM budget_ledgers WHERE thread_id = ?", (tid,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
