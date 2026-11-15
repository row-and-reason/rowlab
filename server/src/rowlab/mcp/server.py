"""The MCP server: the API's data work as tools, for agents. Served at `/mcp` by the API, and over
stdio by `rowlab mcp`. Each tool is a thin call into `core`, as the API's endpoints are.

Hosted, a call is signed in with an API key (`rl_…`) or a WorkOS access token, which MCP clients get
by signing in with WorkOS (AuthKit is the authorization server; `/.well-known/oauth-protected-resource`
says so). A WorkOS token is a JWT checked against AuthKit's keys, issuer and this server's address as
its audience, so a token for another application doesn't do. Locally nothing signs in, as with the API.
"""

import asyncio
import functools
import time
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.auth.providers.workos import AuthKitProvider
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel, Field

from rowlab import __version__
from rowlab.core import auth, catalog, compare, datasets, exports, labels, links, prompts, runs
from rowlab.core import sql as sql_core
from rowlab.core import tasks as tasks_core
from rowlab.core.auth import Me, Role
from rowlab.core.compare import Comparison
from rowlab.core.config import config
from rowlab.core.datasets import AnswerColumn, ColumnProfile, Dataset, DatasetSummary
from rowlab.core.errors import Forbidden, InvalidRequest, NotFound, Unauthorized
from rowlab.core.exports import ExportFormat, ExportRequest, ExportResult
from rowlab.core.links import Link
from rowlab.core.prompts import RenderRequest, RenderResult
from rowlab.core.providers.model_api import ProviderError
from rowlab.core.runs import Estimate, Run, RunRequest
from rowlab.core.sql import ALL_ROWS, QueryRequest, QueryResult
from rowlab.core.tasks import Task, TaskTypes

INSTRUCTIONS = (
    "rowlab asks a question of every row of a dataset with AI models, and lets you compare their "
    "answers with each other and with labels people trust. A dataset is the rows of one file; runs "
    "and people add answer columns to it, and the file's own columns never change. A model's "
    "answers go in `<column>__<model>` (e.g. `fallacy__jev-1.14`); labels people set go in a column "
    "named for them (e.g. `gold`). Answer columns are often sparse: empty means not asked. Rows are "
    "picked with one DuckDB SELECT over the table `data`; the same SQL views, runs on, compares and "
    "exports. Work in this order: read the dataset (dataset_get), pick a sample with a stable order "
    "(`ORDER BY md5('s1' || __row_id) LIMIT 50`: a bigger sample keeps the smaller), run_preview, "
    "then run_start; look at the answers with sql_query and columns_compare them, with each other "
    "and with labels from the file or set by people; adjust the prompt or model; then run_start "
    "the same tasks on all rows: only the answers still missing are asked and paid for. A changed "
    "prompt, options or answer type needs a new column name; put variants side by side as tasks "
    "of one run. To start a stopped or failed run again, start it again: it asks what is missing. "
    "Runs cost money and take time: tell the user the estimate before a run on many rows. People's "
    "labels go in with labels_set, before or after models run, on any rows: the same task the "
    "models do, or a judgement of a model's answer (e.g. a yes/no task 'is fallacy__jev-1.14 "
    "right?'). Only set labels the user gives or explicitly asks you to produce. A file on your "
    "machine goes in with dataset_upload and comes out with dataset_download, through curl. The API "
    "and the Python SDK do the same work, for scripts."
)

DatasetId = Annotated[str, Field(description="A dataset's id, from datasets_list.")]
Sql = Annotated[
    str,
    Field(
        description="One DuckDB SELECT over the table `data`, e.g. "
        "`SELECT * FROM data WHERE stars = 1 LIMIT 20`. All rows by default."
    ),
]
WaitSeconds = Annotated[
    int,
    Field(
        ge=0,
        le=30,
        description="Return once the run is done, or after this many seconds, as it stands.",
    ),
]


class DatasetDetail(Dataset):
    profile: list[ColumnProfile] | None = Field(
        description="Each column's min, max, average, distinct count and share of nulls, if asked."
    )


class RunPreview(BaseModel):
    estimate: Estimate
    rendered: list[RenderResult] = Field(
        description="Each task's prompt rendered for a few rows, with warnings, in task order."
    )


# Replaces the API's status codes: a tool call either works or says what went wrong.
_ERRORS = (InvalidRequest, NotFound, Forbidden, Unauthorized, ProviderError)


def _me(role: Role = "verifier") -> Me:
    """Who is calling, with at least `role`. Locally, the one implicit admin."""
    if config().mode == "local":
        return auth.LOCAL
    token = get_access_token()
    if token is None:
        raise Unauthorized("Sign in, or send an API key: `Authorization: Bearer rl_…`.")
    if "rowlab" in token.claims:
        me = Me.model_validate(token.claims["rowlab"])
    else:
        me = auth.me_for_workos_user(token.claims["sub"])
    auth.require(me, role)
    return me


class _Verifier(TokenVerifier):
    """Takes rowlab's own API keys as well as WorkOS tokens."""

    def __init__(self, workos: JWTVerifier):
        super().__init__()
        self._workos = workos

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith(auth.API_KEY_PREFIX):
            return await self._workos.verify_token(token)
        try:
            me = await asyncio.to_thread(auth.authenticate, None, token)
        except Unauthorized:
            return None
        return AccessToken(
            token=token, client_id=me.user.id, scopes=[], claims={"rowlab": me.model_dump()}
        )


def create_server() -> FastMCP:
    provider = None
    if config().mode == "hosted":
        domain = config().workos_authkit_domain
        workos = JWTVerifier(
            jwks_uri=f"{domain}/oauth2/jwks",
            issuer=domain,
            algorithm="RS256",
            # Tokens are for this server: the resource `/.well-known/oauth-protected-resource/mcp`
            # names, which the WorkOS dashboard must list as a resource indicator.
            audience=f"{config().url}/mcp",
        )
        provider = AuthKitProvider(
            authkit_domain=domain,
            base_url=config().url,
            resource_name="rowlab",
            token_verifier=_Verifier(workos),
        )
    mcp = FastMCP("rowlab", instructions=INSTRUCTIONS, version=__version__, auth=provider)

    def tool(fn: Any) -> Any:
        """Register a tool whose core errors become tool errors, with their message."""

        @functools.wraps(fn)
        def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except _ERRORS as e:
                raise ToolError(str(e)) from e

        return mcp.tool(call)

    @tool
    def datasets_list() -> list[DatasetSummary]:
        """Every dataset: its name, rows, how many answer columns it has and runs going. The starting
        point: find the dataset to work on, then dataset_get it for its columns."""
        return datasets.list_datasets(_me().org.id)

    @tool
    def dataset_get(
        dataset_id: DatasetId,
        profile: Annotated[
            bool, Field(description="Also profile every column (slower on big datasets).")
        ] = False,
    ) -> DatasetDetail:
        """One dataset in full: every column with its type, and its answer columns: the task each
        answers, the model or labels, how many rows have an answer and what it cost. Read it before
        writing SQL or a prompt, so column names and types are right; profile it to know the values."""
        me = _me()
        datasets.check_access(me.org.id, dataset_id)
        dataset = datasets.get_dataset(dataset_id)
        found = datasets.profile_dataset(dataset_id) if profile else None
        return DatasetDetail(**dataset.model_dump(), profile=found)

    @tool
    def dataset_add(
        source: Annotated[
            str,
            Field(
                description="A public http(s) URL or an `s3://bucket/key` object; locally, also a "
                "path on this machine. CSV, TSV, JSON, JSONL or Parquet, gzipped or not."
            ),
        ],
        connection_id: Annotated[
            str | None, Field(description="For private buckets: a storage connection's id.")
        ] = None,
    ) -> Dataset:
        """Add a dataset from a URL, S3 or a file. Use it when the data isn't in rowlab yet; the
        result lists the columns, so the next step is a prompt or a query. For a file on your
        machine on hosted rowlab, use dataset_upload."""
        me = _me("member")
        return datasets.create_dataset(me.org.id, source, connection_id)

    @tool
    def dataset_upload() -> Link:
        """A link to upload a file on your machine as a dataset, for when it has no public URL:
        run its `command` with the file's path; curl prints the new dataset. CSV, TSV, JSON, JSONL
        or Parquet, gzipped or not. Hosted rowlab; the link works for 15 minutes."""
        me = _me("member")
        return links.upload_link(me.org.id)

    @tool
    def dataset_rename(dataset_id: DatasetId, name: str) -> Dataset:
        """Give a dataset a descriptive display name. Its id and data stay the same."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        return datasets.rename_dataset(dataset_id, datasets.RenameDataset(name=name))

    @tool
    def dataset_delete(dataset_id: DatasetId) -> None:
        """Delete a dataset with all its answers and runs, when the user asks."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        datasets.delete_dataset(dataset_id)

    @tool
    def sql_query(
        dataset_id: DatasetId,
        sql: Sql = ALL_ROWS,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
    ) -> QueryResult:
        """A page of what a SELECT over `data` returns, with the total. The way to look at rows and
        answers: it can read nothing but the dataset. `agree([a, b])` and `disagree([a, b])`
        compare columns in a row. The same SQL picks the rows for a run or an export."""
        me = _me()
        datasets.check_access(me.org.id, dataset_id)
        return sql_core.query(dataset_id, QueryRequest(sql=sql, offset=offset, limit=limit))

    @tool
    def columns_compare(
        dataset_id: DatasetId,
        columns: Annotated[
            list[str], Field(description="Two or more columns; or one, with a reference.")
        ],
        reference: Annotated[
            str | None, Field(description="Labels you trust, to measure the others against.")
        ] = None,
        tolerance: Annotated[
            float | None,
            Field(
                ge=0,
                allow_inf_nan=False,
                description="For numbers or dates: maximum absolute difference (days for dates).",
            ),
        ] = None,
        ignore_case: Annotated[
            bool, Field(description="Unicode lowercase matching for text columns.")
        ] = False,
        trim_whitespace: Annotated[
            bool, Field(description="Trim surrounding ASCII whitespace in text columns.")
        ] = False,
        sql: Sql = ALL_ROWS,
        rows: Annotated[
            Literal["common", "pairwise"],
            Field(
                description="common: every statistic on the rows where all the columns have a "
                "value, so they are measured alike. pairwise: each on its own columns' rows."
            ),
        ] = "common",
        detail: Annotated[
            Literal["summary", "full"],
            Field(
                description="Summary keeps per-class precision/recall; full adds distributions and drill-down filters."
            ),
        ] = "summary",
    ) -> Comparison | dict[str, Any]:
        """How often columns give the same value per row: models against each other, or against
        labels you trust, with each column's accuracy and Wilson intervals. It says first how many
        rows each column has a value in, and how many were left out: read that before the numbers.
        Use it to pick a model or judge quality; request detail="full" for every count's `where`
        clause and full distributions."""
        me = _me()
        datasets.check_access(me.org.id, dataset_id)
        request = compare.CompareRequest(
            columns=columns,
            reference=reference,
            tolerance=tolerance,
            ignore_case=ignore_case,
            trim_whitespace=trim_whitespace,
            sql=sql,
            rows=rows,
        )
        result = compare.compare(dataset_id, request)
        return result if detail == "full" else compare.compact_comparison(result)

    @tool
    def run_preview(
        dataset_id: DatasetId,
        tasks: Annotated[list[Task], Field(description="As for run_start.")],
        sql: Sql = ALL_ROWS,
    ) -> RunPreview:
        """What a run would do before it does: rows, answers it would ask for and those it has
        already, rough cost in USD, the prompt rendered for a few rows with warnings, and what
        stops it running. Catches a bad prompt or a surprise cost before money is spent: call it
        before every run_start, and tell the user the cost before a run on many rows."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        request = RunRequest(sql=sql, tasks=tasks)
        rendered = [
            prompts.render_dataset(dataset_id, RenderRequest(template=t.template, sql=sql, limit=2))
            for t in tasks
        ]
        return RunPreview(estimate=runs.estimate(dataset_id, request), rendered=rendered)

    @tool
    def run_start(
        dataset_id: DatasetId,
        tasks: Annotated[
            list[Task],
            Field(
                description="Each needs a `template` (the question, with `{{column}}` for a row's "
                "values) and a `type`; the result column and models default to ones that suit "
                "the type (task_types_get)."
            ),
        ],
        sql: Sql = ALL_ROWS,
        wait_seconds: WaitSeconds = 0,
    ) -> Run:
        """Ask every task of every model about the rows the SQL picks, adding the answers to the
        dataset as columns `<column>__<model>`. Only answers the dataset doesn't have are asked,
        so start on a sample, look, then run the same tasks on all rows and pay only for the rest;
        to start a stopped or failed run again, start it again. Rows missing a value the prompt
        uses are skipped. Small runs finish within `wait_seconds`; poll the rest with run_get."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        run = runs.create_run(
            dataset_id, RunRequest(sql=sql, tasks=tasks), me.user.id if me.user else None
        )
        return _wait(run, wait_seconds)

    @tool
    def runs_list(dataset_id: DatasetId) -> list[Run]:
        """The dataset's runs, newest first: what each asked, its status, progress and cost."""
        me = _me()
        datasets.check_access(me.org.id, dataset_id)
        return runs.list_runs(dataset_id)

    @tool
    def labels_set(
        dataset_id: DatasetId,
        column: Annotated[str, Field(description="The labels' column, e.g. `gold`.")],
        labels_: Annotated[
            list[labels.Label],
            Field(alias="labels", description="Rows and their labels; a null label clears it."),
        ],
        task: Annotated[
            Task | None,
            Field(
                description="The question the labels answer: needed with a column's first labels, "
                "e.g. the same task the models do, or a yes/no judgement of a model's answer."
            ),
        ] = None,
    ) -> AnswerColumn:
        """Set labels people give, on any rows, before or after models are asked: yes/no takes
        true or false, pick one and scale an option's name, pick any a list of names, write text,
        extract an object keyed by field name. No model is called. Only set labels the user gives
        or explicitly asks you to produce. Read them with sql_query; compare models with them with
        columns_compare."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        return labels.set_labels(
            dataset_id,
            column,
            labels.SetLabels(task=task, labels=labels_),
            me.user.id if me.user else None,
        )

    @tool
    def answers_delete(
        dataset_id: DatasetId,
        column: Annotated[str, Field(description="The task's column, e.g. `fallacy`.")],
        model: Annotated[
            str | None, Field(description="The model, e.g. `typesafe/jev-1.14`; none for labels.")
        ] = None,
    ) -> None:
        """Delete a task's answers from one model, or a column of labels, when the user asks: e.g.
        a try they no longer want. Model replies are kept, so asking the same again is free."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        datasets.delete_answers(dataset_id, column, model)

    @tool
    def run_get(run_id: str, wait_seconds: WaitSeconds = 0) -> Run:
        """A run's status, progress (`done` of `total` calls), cost and failed answers. Poll it
        while a run goes; its dataset's rows fill in meanwhile."""
        me = _me()
        runs.check_access(me.org.id, run_id)
        return _wait(runs.get_run(run_id), wait_seconds)

    @tool
    def run_stop(run_id: str) -> Run:
        """Stop a run after the calls in flight, e.g. when the first answers look wrong. Starting
        it again later asks for what it didn't get to; what it paid for stays free."""
        me = _me("member")
        runs.check_access(me.org.id, run_id)
        return runs.stop_run(run_id)

    @tool
    def dataset_export(
        dataset_id: DatasetId,
        format: ExportFormat,
        path: Annotated[
            str,
            Field(
                description="An `s3://bucket/key` object (with a connection for private buckets) "
                "or, locally, a path on this machine. A folder gets a file named after the "
                "dataset."
            ),
        ],
        connection_id: str | None = None,
        sql: Annotated[
            str | None, Field(description="Only the rows this SELECT picks; all by default.")
        ] = None,
        include_row_id: Annotated[bool, Field(description="Keep rowlab's `__row_id`.")] = False,
    ) -> ExportResult:
        """Write a dataset, or the rows a SELECT picks, as CSV, JSONL or Parquet, to S3 or a local
        file. The last step: hand the user the data with its answer columns, where they use it. To
        your own machine on hosted rowlab, use dataset_download."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        request = ExportRequest(
            format=format,
            path=path,
            connection_id=connection_id,
            sql=sql,
            include_row_id=include_row_id,
        )
        return exports.export_to_path(dataset_id, request)

    @tool
    def dataset_download(
        dataset_id: DatasetId,
        format: ExportFormat,
        sql: Annotated[
            str | None, Field(description="Only the rows this SELECT picks; all by default.")
        ] = None,
        include_row_id: Annotated[bool, Field(description="Keep rowlab's `__row_id`.")] = False,
    ) -> Link:
        """A link to download a dataset, or the rows a SELECT picks, as CSV, JSONL or Parquet to
        your machine: run its `command`. Hosted rowlab; the link works for 15 minutes. The last
        step, like dataset_export, when the user wants the file where you are."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        return links.download_link(dataset_id, format, include_row_id=include_row_id, query=sql)

    @tool
    def task_types_get() -> TaskTypes:
        """The answer types a task can have (classify: yes/no, pick one, pick any, scale; extract:
        typed fields; write: free text), their defaults, presets like Summarise and Translate, and
        which models suit each. Read once before writing tasks."""
        _me()
        return tasks_core.task_types()

    @tool
    def models_list(
        search: Annotated[str, Field(description="Part of a model's id or name.")] = "",
        kind: Annotated[
            Literal["decision", "llm"] | None,
            Field(description="Decision models (fast, cheap, classify only) or LLMs."),
        ] = None,
        tag: Annotated[
            str | None,
            Field(description="Only models with this tag: `recommended`, `budget` or `accurate`."),
        ] = None,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> catalog.ModelPage:
        """A page of the models rowlab offers, with per-token prices, in the order we'd pick them.
        Search by name, kind or tag; follow next_offset for more. Defaults from task_types_get are
        fine to start with."""
        _me()
        return catalog.list_models(search, kind, tag, offset, limit)

    return mcp


def _wait(run: Run, seconds: int) -> Run:
    """The run as it stands once done, or after `seconds`."""
    until = time.monotonic() + seconds
    while run.status in datasets.ACTIVE and time.monotonic() < until:
        time.sleep(0.5)
        run = runs.get_run(run.id)
    return run
