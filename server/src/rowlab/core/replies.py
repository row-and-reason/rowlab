"""Model replies, kept so a paid call is not made twice, without the database growing with every row.

A run writes each chunk's replies beside the dataset: `replies/{run}/part-{k}.parquet`, with
`__row_id`, the request's `key` (a hash of the organisation and the request, with rowlab's model id)
and the reply's `data`. When the run ends (done, stopped or failed) they are written out as one
`replies/{run}.parquet`, sorted by `__row_id`, with those it paid for in a chunk it didn't get to
write. They are deleted with the dataset, and kept when its answers are deleted, so asking the same
again is free. Only replies that could be read as an answer are kept.

Before asking, a run looks for each request's reply among those of the dataset's other runs that used
the same models, read only around the chunk's rows. The database only keeps the replies of chunks under
way (`answer_journal`), so a stop or crash before a chunk is written doesn't pay for them again either;
they are cleared once the chunk is written.
"""

import hashlib
import json
from typing import Any

from rowlab.core import db, storage
from rowlab.core.datasets import ACTIVE, ROW_ID
from rowlab.core.providers.model_api import Request
from rowlab.core.storage import sql_ident, sql_string

# Rows per row group of `replies/{run}.parquet`: a chunk's lookup reads about one group of each file.
ROW_GROUP_ROWS = 5000

# A reply: its key, the row it is for, and its data.
Reply = tuple[str, int, Any]


def key(org_id: str, request: Request) -> str:
    """The same request from the same organisation gets the same key; each organisation has its
    own replies, which nobody else sees or gets for free. The model is named by rowlab's id, not the
    name its provider gives it: two checkpoints served under one name are two models, and a catalog
    model's reply is kept for it through any provider that asks it the same way (an LLM's chat
    completion through OpenRouter or a gateway; decisions differ by API)."""
    body = request.body | {"model": request.model}
    return hashlib.sha256(
        json.dumps({"org": org_id, "path": request.path, "body": body}, sort_keys=True).encode()
    ).hexdigest()


def journaled(run_id: str) -> dict[str, Any]:
    """The replies the run paid for in chunks not yet written, by key."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT key, data FROM answer_journal WHERE run_id = ?", (run_id,)
        ).fetchall()
    return {r["key"]: json.loads(r["data"]) for r in rows}


def stored(dataset_id: str, models: list[str], row_ids: list[int]) -> dict[str, Any]:
    """Replies kept by the dataset's runs that used any of `models`, for rows in the range of
    `row_ids`, by key. One file per run, read only around those rows."""
    with db.connect() as conn:
        runs = conn.execute(
            "SELECT id, status, next_chunk, config FROM runs WHERE dataset_id = ?", (dataset_id,)
        ).fetchall()
    files = [
        file
        for r in runs
        if set(models) & {m for task in json.loads(r["config"])["tasks"] for m in task["models"]}
        for file in _files(dataset_id, r["id"], r["status"], r["next_chunk"])
    ]
    if not files or not row_ids:
        return {}
    with storage.connect() as con:
        rows = con.execute(
            f"SELECT key, data FROM read_parquet([{', '.join(map(sql_string, files))}])"
            f" WHERE {sql_ident(ROW_ID)} BETWEEN ? AND ?",
            [min(row_ids), max(row_ids)],
        ).fetchall()
    return {k: json.loads(data) for k, data in rows}


def _files(dataset_id: str, run_id: str, status: str, chunks: int) -> list[str]:
    if status in ACTIVE:
        return [_part(dataset_id, run_id, k) for k in range(chunks)]
    return [storage.location(dataset_id, "replies", f"{run_id}.parquet")]


def _part(dataset_id: str, run_id: str, chunk: int) -> str:
    return storage.location(dataset_id, "replies", run_id, f"part-{chunk:06d}.parquet")


def journal(run_id: str, replies: list[Reply]) -> None:
    """Keep replies just paid for until their chunk is written."""
    if not replies:
        return
    with db.connect() as conn:
        for reply_key, row_id, data in replies:
            conn.execute(
                "INSERT INTO answer_journal (run_id, key, row_id, data) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (run_id, key) DO UPDATE SET data = excluded.data",
                (run_id, reply_key, row_id, json.dumps(data)),
            )


def clear_journal(run_id: str, row_ids: list[int]) -> None:
    """Forget the run's journaled replies for a chunk's rows, once it is written with them. A
    chunk's rows are a range of `__row_id`s no other chunk's overlap."""
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM answer_journal WHERE run_id = ? AND row_id BETWEEN ? AND ?",
            (run_id, min(row_ids), max(row_ids)),
        )


def write_part(dataset_id: str, run_id: str, chunk: int, replies: list[Reply]) -> None:
    """Write a chunk's replies, as the chunk's answers are written."""
    with storage.connect() as con:
        con.execute(f"CREATE TABLE replies ({sql_ident(ROW_ID)} BIGINT, key VARCHAR, data VARCHAR)")
        if replies:
            con.executemany(
                "INSERT INTO replies VALUES (?, ?, ?)",
                [(row_id, k, json.dumps(data)) for k, row_id, data in replies],
            )
        storage.write(
            con,
            f"SELECT * FROM replies ORDER BY {sql_ident(ROW_ID)}",
            _part(dataset_id, run_id, chunk),
        )


def finish(dataset_id: str, run_id: str, chunks: int) -> None:
    """Write an ended run's replies out as one file, sorted by `__row_id` so lookups read little of
    it, with those still journaled, which the journal then forgets. Its parts are deleted once the
    run is marked ended (`delete_parts`)."""
    journaled = _journaled_rows(run_id)
    parts = ", ".join(sql_string(_part(dataset_id, run_id, k)) for k in range(chunks))
    with storage.connect() as con:
        con.execute(f"CREATE TABLE replies ({sql_ident(ROW_ID)} BIGINT, key VARCHAR, data VARCHAR)")
        if chunks:
            con.execute(f"INSERT INTO replies SELECT * FROM read_parquet([{parts}])")
        if journaled:
            con.executemany("INSERT INTO replies VALUES (?, ?, ?)", journaled)
        storage.write(
            con,
            f"SELECT * FROM replies ORDER BY {sql_ident(ROW_ID)}",
            storage.location(dataset_id, "replies", f"{run_id}.parquet"),
            row_group_size=ROW_GROUP_ROWS,
        )
    with db.connect() as conn:
        conn.execute("DELETE FROM answer_journal WHERE run_id = ?", (run_id,))


def _journaled_rows(run_id: str) -> list[tuple[int, str, str]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT row_id, key, data FROM answer_journal WHERE run_id = ?", (run_id,)
        ).fetchall()
    return [(r["row_id"], r["key"], r["data"]) for r in rows]


def delete_parts(dataset_id: str, run_id: str, chunks: int) -> None:
    for k in range(chunks):
        storage.delete(_part(dataset_id, run_id, k))
