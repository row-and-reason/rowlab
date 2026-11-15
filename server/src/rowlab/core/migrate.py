"""`rowlab migrate`: fold the old layout, where a run made a new dataset in a tree, into one dataset
per file, in place. Run once, with runners stopped; a follow-up deletes this module with migration 009.

For each tree, the root keeps its id, name and `data.parquet`. Each dataset made from it gives its own
columns (those its parent doesn't have) to the root: a model run's as `runs/{run}.parquet` with its
replies as `replies/{run}.parquet`, a manual run's as labels. Runs move to the root, still or stopped;
manual runs are deleted. The same task and model in two runs is one answer column; a name taken by
another question gets a suffix. A root whose parent was deleted keeps the columns it got from its
ancestors in its file, and gives its own like the others.

Files are written first, then the database in one transaction, then old folders are deleted, so an
interrupted migrate can be run again. `--dry-run` only says what it would do.
"""

import json
from datetime import UTC, datetime
from typing import Any

from rowlab.core import datasets, db, storage, tasks
from rowlab.core.datasets import ROW_ID
from rowlab.core.errors import InvalidRequest
from rowlab.core.storage import sql_ident, sql_string
from rowlab.core.tasks import Task

# The old layout's chunk size and the column its parts listed failed answers in.
OLD_CHUNK_ROWS = 500
OLD_FAILED = "__failed"

# Old statuses of a run that hadn't ended: it ends stopped, and starting it again goes on.
STOPPED = ("queued", "running", "stopping")


def pending() -> int:
    """Datasets still in the old layout's trees."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM datasets WHERE parent_id IS NOT NULL"
        ).fetchone()["n"]


def migrate(dry_run: bool = False) -> None:
    """Fold every tree into its root, printing what is done (or, with `dry_run`, would be)."""
    with db.connect() as conn:
        found = conn.execute("SELECT * FROM datasets ORDER BY created_at, id").fetchall()
        runs = conn.execute("SELECT * FROM runs").fetchall()
    ids = {d["id"] for d in found}
    run_of = {r["dataset_id"]: r for r in runs}
    children: dict[str, list[dict]] = {}
    for d in found:
        if d["parent_id"] in ids:
            children.setdefault(d["parent_id"], []).append(d)

    trees = 0
    for root in found:
        if root["parent_id"] in ids or (root["parent_id"] is None and root["id"] not in children):
            continue
        made: list[dict] = []
        below = list(children.get(root["id"], []))
        while below:
            d = below.pop()
            made.append(d)
            below += children.get(d["id"], [])
        made.sort(key=lambda d: (d["created_at"], d["id"]))
        _fold(root, made, {d["id"]: d for d in found}, run_of, dry_run)
        trees += 1
    print(f"{trees} tree(s) {'to fold' if dry_run else 'folded'}.")


def _fold(
    root: dict, made: list[dict], by_id: dict[str, dict], run_of: dict[str, dict], dry_run: bool
) -> None:
    root_id = root["id"]
    orphan = root["parent_id"] is not None
    print(
        f"{root['name']} ({root_id}): {len(made)} dataset(s) made from it"
        + (", and it was made from a deleted one" if orphan else "")
    )
    folded = ([root] if orphan else []) + made
    snapshot = storage.location(root_id, "old-data.parquet")
    columns: dict[str, list[tuple[str, str]]] = {}  # Each dataset's old columns.

    def source(d: dict) -> str:
        """The old rows of a dataset, made by a run or not."""
        if d["id"] == root_id and orphan and storage.exists(snapshot):
            return f"read_parquet({sql_string(snapshot)})"
        run = run_of.get(d["id"])
        return _old_source(d["id"], run["status"] if run else None)

    def describe(d: dict) -> list[tuple[str, str]]:
        if d["id"] not in columns:
            with storage.connect() as con:
                columns[d["id"]] = [
                    (r[0], r[1])
                    for r in con.execute(f"DESCRIBE SELECT * FROM {source(d)}").fetchall()
                ]
        return columns[d["id"]]

    def own(d: dict) -> list[str]:
        """A made dataset's own columns: those its parent doesn't have. A root whose parent was
        deleted has its run's."""
        names = [name for name, _ in describe(d)]
        if d["parent_id"] in by_id:
            parent = {name for name, _ in describe(by_id[d["parent_id"]])}
            return [n for n in names if n not in parent and n != ROW_ID]
        run = run_of.get(d["id"])
        if run is None:
            return []
        written = {name for task in _tasks(run) for name in _names(task, _models(task))}
        return [n for n in names if n in written]

    # A root made from a deleted dataset keeps its old rows, until the database says it's folded.
    if orphan and not dry_run and not storage.exists(snapshot):
        with storage.connect() as con:
            storage.write(con, f"SELECT * FROM {source(root)}", snapshot)
    if orphan:
        root_columns = [c for c in describe(root) if c[0] not in own(root)]
    else:
        root_columns = [(c["name"], c["type"]) for c in json.loads(root["columns"])]

    # The answer columns the root has: what they answer, and the names they take.
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name, model, task FROM answer_columns WHERE dataset_id = ?", (root_id,)
        ).fetchall()
    registry = {}
    taken = {name for name, _ in root_columns}
    for r in rows:
        task = Task.model_validate_json(r["task"])
        registry[(r["name"], r["model"])] = datasets.definition(task)
        taken.update(_names(task, [r["model"] or None]))
    existing = set(registry)

    new_answers: dict[tuple[str, str], tuple[str, str]] = {}  # (name, model): (task, created_at)
    written: dict[tuple[str, str], list[tuple[str, str]]] = {}  # (name, model): [(file, column)]
    run_updates = []
    manual_runs = []
    labels: dict[tuple[str, int], tuple[str, str | None, str]] = {}
    for d in folded:
        run = run_of.get(d["id"])
        if run is None:
            print(f"  {d['name']}: no run, nothing to keep")
            continue
        manual = json.loads(run["config"]).get("method") == "manual"
        placed = []
        renamed = {}  # Old column: new.
        for task in _tasks(run):
            models = _models(task)
            new = _place(task, models, registry, taken)
            if new.column != task.column:
                print(f"  `{task.column}` of run {run['id']} is `{new.column}`: the name was taken")
            for model in models:
                key = (new.column, model or "")
                if key not in new_answers and key not in existing:
                    dumped = new.model_copy(update={"models": []}).model_dump_json()
                    new_answers[key] = (dumped, run["created_at"])
            renamed |= dict(zip(_names(task, models), _names(new, models)))
            placed.append((task, new))
        kept = [c for c in own(d) if c in renamed]
        dropped = [c for c in own(d) if c not in renamed]
        if dropped:
            print(f"  {d['name']}: no task writes {', '.join(dropped)}, left out")

        if manual:
            found = _labels(source(d), kept, placed, run)
            labels |= found
            manual_runs.append(run["id"])
            names = sorted({new.column for _, new in placed})
            print(f"  {d['name']}: manual run {run['id']}, {len(found)} label(s) in {names}")
            continue

        status = "stopped" if run["status"] in STOPPED else run["status"]
        replies_count = _write_run(root_id, d, run, source(d), kept, renamed, dry_run)
        file = storage.location(root_id, "runs", f"{run['id']}.parquet")
        for _, new in placed:
            for model in new.models:
                first = tasks.columns(new, model)[0][0]
                if first in {renamed[c] for c in kept}:
                    written.setdefault((new.column, model), []).append((file, first))
        config = json.loads(run["config"])
        config = {k: v for k, v in config.items() if k == "sql"} | {
            "tasks": [new.model_dump(mode="json") for _, new in placed]
        }
        run_updates.append(
            (
                root_id,
                status,
                json.dumps(config),
                json.dumps([c for _, new in placed for c in tasks.result_columns(new)]),
                run["id"],
            )
        )
        print(
            f"  {d['name']}: run {run['id']} ({run['status']}"
            + (f", now {status}" if status != run["status"] else "")
            + f"), {len(kept)} column(s), {replies_count} kept replies"
        )

    if dry_run:
        return
    answered = _answered(written)
    root_update = None
    if orphan:
        root_update = _write_root(root_id, snapshot, own(root))
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        for (name, model), (task, created_at) in new_answers.items():
            conn.execute(
                "INSERT INTO answer_columns (dataset_id, name, model, task, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (root_id, name, model, task, created_at),
            )
        for (name, model), n in answered.items():
            conn.execute(
                "UPDATE answer_columns SET answered = ? WHERE dataset_id = ? AND name = ?"
                " AND model = ?",
                (n, root_id, name, model),
            )
        for update in run_updates:
            conn.execute(
                "UPDATE runs SET dataset_id = ?, status = ?, config = ?, columns = ?,"
                " retry_chunk = NULL WHERE id = ?",
                update,
            )
            conn.execute("DELETE FROM answer_journal WHERE run_id = ?", (update[-1],))
        for (name, row_id), (value, set_by, updated_at) in labels.items():
            conn.execute(
                "INSERT INTO labels (dataset_id, name, row_id, value, set_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (root_id, name, row_id, value, set_by, updated_at or now),
            )
        for run_id in manual_runs:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        if root_update:
            conn.execute(
                "UPDATE datasets SET columns = ?, row_count = ?, size_bytes = ? WHERE id = ?",
                (*root_update, root_id),
            )
        conn.execute("UPDATE datasets SET parent_id = NULL, branch = NULL WHERE id = ?", (root_id,))
        for d in made:
            conn.execute("DELETE FROM datasets WHERE id = ?", (d["id"],))
    for d in made:
        storage.delete_dataset(d["id"])
    if orphan:
        with storage.connect() as con:
            old = [
                r[0]
                for pattern in ("parts/*.parquet", "answers/*.parquet")
                for r in con.execute(
                    "SELECT file FROM glob(?)", [storage.location(root_id, pattern)]
                ).fetchall()
            ]
        for name in ("old-data.parquet", "rows.parquet", "asked.parquet", "answers.parquet"):
            old.append(storage.location(root_id, name))
        for file in old:
            storage.delete(file)


def _tasks(run: dict) -> list[Task]:
    """A run's tasks; a manual run's as labels take them, asking no models."""
    config = json.loads(run["config"])
    found = [Task.model_validate(t) for t in config["tasks"]]
    if config.get("method") == "manual":
        return [t.model_copy(update={"models": [], "reason": False}) for t in found]
    return found


def _models(task: Task) -> list[str | None]:
    """The models whose answers a run's task wrote; None for a manual run's labels."""
    return list(task.models) if task.models else [None]


def _names(task: Task, models: list[str | None]) -> list[str]:
    """The columns a task's answers from `models` (None for labels) have, in order."""
    return [
        name
        for model in models
        for name, _ in (tasks.label_columns(task) if model is None else tasks.columns(task, model))
    ]


def _place(
    task: Task, models: list[str | None], registry: dict[tuple[str, str], Any], taken: set[str]
) -> Task:
    """The task as the root has it: under its own name, if that is free or answers the same
    question, or else the first free `name_2`, `name_3`, …. Records its answer columns."""
    n = 1
    while True:
        new = task if n == 1 else task.model_copy(update={"column": f"{task.column}_{n}"})
        fits = True
        for model in models:
            known = registry.get((new.column, model or ""))
            if known is not None:
                fits = fits and known == datasets.definition(new)
            else:
                fits = fits and not set(_names(new, [model])) & taken
        if fits:
            break
        n += 1
    for model in models:
        if (new.column, model or "") not in registry:
            registry[(new.column, model or "")] = datasets.definition(new)
            taken.update(_names(new, [model]))
    return new


def _old_source(dataset_id: str, status: str | None) -> str:
    """A DuckDB table expression for a dataset's rows in the old layout: its `data.parquet`, or, for
    one a run was still making, its rows joined with the answers written so far."""
    data = storage.location(dataset_id, "data.parquet")
    if status != "manual" and storage.exists(data):
        return f"read_parquet({sql_string(data)})"
    rows = sql_string(storage.location(dataset_id, "rows.parquet"))
    parts = sql_string(storage.location(dataset_id, "parts", "*.parquet"))
    return (
        f"(SELECT {ROW_ID}, a.* EXCLUDE ({ROW_ID}, {OLD_FAILED}), r.* EXCLUDE ({ROW_ID}) "
        f"FROM read_parquet({rows}) AS r "
        f"LEFT JOIN read_parquet({parts}) AS a USING ({ROW_ID}))"
    )


def _write_run(
    root_id: str,
    d: dict,
    run: dict,
    source: str,
    kept: list[str],
    renamed: dict[str, str],
    dry_run: bool,
) -> int:
    """Write a model run's answers, the rows it asked about and its kept replies where the root's
    runs keep them. Returns how many replies it kept."""
    run_id = run["id"]
    old_replies = storage.location(d["id"], "answers.parquet")
    asked = storage.location(d["id"], "asked.parquet")
    with db.connect() as conn:
        journaled = [
            (r["row_id"], r["key"], r["data"])
            for r in conn.execute(
                "SELECT row_id, key, data FROM answer_journal WHERE run_id = ?", (run_id,)
            ).fetchall()
        ]
    with storage.connect() as con:
        files = [
            r[0]
            for r in con.execute(
                "SELECT file FROM glob(?)", [storage.location(d["id"], "answers", "*.parquet")]
            ).fetchall()
        ]
        if storage.exists(old_replies):
            files.append(old_replies)
        con.execute(f"CREATE TABLE replies ({sql_ident(ROW_ID)} BIGINT, key VARCHAR, data VARCHAR)")
        if files:
            con.execute(
                f"INSERT INTO replies SELECT {ROW_ID}, key, data"
                f" FROM read_parquet([{', '.join(map(sql_string, files))}])"
            )
        if journaled:
            con.executemany("INSERT INTO replies VALUES (?, ?, ?)", journaled)
        count = con.execute("SELECT count(*) FROM (SELECT DISTINCT * FROM replies)").fetchone()[0]
        if dry_run:
            return count
        storage.write(
            con,
            f"SELECT DISTINCT * FROM replies ORDER BY {ROW_ID}",
            storage.location(root_id, "replies", f"{run_id}.parquet"),
            row_group_size=5000,
        )
        select = ", ".join([ROW_ID, *(f"{sql_ident(c)} AS {sql_ident(renamed[c])}" for c in kept)])
        storage.write(
            con,
            f"SELECT {select} FROM {source} ORDER BY {ROW_ID}",
            storage.location(root_id, "runs", f"{run_id}.parquet"),
        )
        rows = f"read_parquet({sql_string(asked)})" if storage.exists(asked) else source
        storage.write(
            con,
            f"SELECT {ROW_ID}, ((row_number() OVER (ORDER BY {ROW_ID}) - 1)"
            f" // {OLD_CHUNK_ROWS})::INTEGER AS chunk FROM {rows} ORDER BY {ROW_ID}",
            storage.location(root_id, "runs", run_id, "asked.parquet"),
        )
    return count


def _labels(
    source: str, kept: list[str], placed: list[tuple[Task, Task]], run: dict
) -> dict[tuple[str, int], tuple[str, str | None, str]]:
    """A manual run's labels, as the labels table keeps them, by column and row."""
    if not kept:
        return {}
    select = ", ".join([ROW_ID, *map(sql_ident, kept)])
    with storage.connect() as con:
        rows = [
            json.loads(r[0])
            for r in con.execute(
                f"SELECT to_json(t) FROM (SELECT {select} FROM {source}) AS t"
            ).fetchall()
        ]
    found = {}
    for row in rows:
        for task, new in placed:
            cells = [row.get(name) for name, _ in tasks.label_columns(task)]
            if all(c is None for c in cells):
                continue
            if task.type == "pick_any":
                value: Any = [o.name for o, c in zip(task.options, cells) if c]
            elif task.type == "extract":
                value = {f.name: c for f, c in zip(task.fields, cells)}
            else:
                value = cells[0]
            try:
                tasks.read_label(new, value)
            except InvalidRequest as e:
                print(f"  label of row {row[ROW_ID]} in `{new.column}` left out: {e}")
                continue
            found[(new.column, row[ROW_ID])] = (
                json.dumps(value, ensure_ascii=False),
                run["created_by"],
                run["updated_at"] or run["created_at"],
            )
    return found


def _answered(written: dict[tuple[str, str], list[tuple[str, str]]]) -> dict[tuple[str, str], int]:
    """Rows with an answer, per answer column, in the run files written."""
    found = {}
    with storage.connect() as con:
        for key, files in written.items():
            union = " UNION ".join(
                f"SELECT {ROW_ID} FROM read_parquet({sql_string(f)}) WHERE {sql_ident(c)} IS NOT NULL"
                for f, c in files
            )
            found[key] = con.execute(f"SELECT count(*) FROM ({union})").fetchone()[0]
    return found


def _write_root(root_id: str, snapshot: str, own: list[str]) -> tuple[str, int, int]:
    """Write a root made from a deleted dataset as a file of its own, without its run's columns.
    Returns its columns, rows and size, as the database keeps them."""
    data = storage.location(root_id, "data.parquet")
    exclude = f" EXCLUDE ({', '.join(map(sql_ident, own))})" if own else ""
    with storage.connect() as con:
        storage.write(
            con,
            f"SELECT *{exclude} FROM read_parquet({sql_string(snapshot)}) ORDER BY {ROW_ID}",
            data,
        )
        relation = f"read_parquet({sql_string(data)})"
        columns = [
            {"name": r[0], "type": r[1]}
            for r in con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        ]
        rows = con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    return json.dumps(columns), rows, storage.size(data)
