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
from rowlab.core import auth, compare, datasets, exports, prompts, runs
from rowlab.core import sql as sql_core
from rowlab.core import tasks as tasks_core
from rowlab.core.auth import Me, Role
from rowlab.core.compare import Comparison
from rowlab.core.config import config
from rowlab.core.datasets import ColumnProfile, Dataset
from rowlab.core.errors import Forbidden, InvalidRequest, NotFound, Unauthorized
from rowlab.core.exports import ExportFormat, ExportRequest, ExportResult
from rowlab.core.prompts import RenderRequest, RenderResult
from rowlab.core.providers import openrouter
from rowlab.core.runs import Estimate, Run, RunRequest
from rowlab.core.sql import ALL_ROWS, QueryRequest, QueryResult
from rowlab.core.tasks import Task, TaskTypes

INSTRUCTIONS = (
    "rowlab labels tabular data with AI: it asks a question of every row of a dataset and writes "
    "the answers as new columns. A run never changes a dataset; it makes a new one, with every row "
    "of the original and the answer columns added, named after its place in the tree (reviews__1, "
    "reviews__1.2). Rows are picked with one DuckDB SELECT over the table `data`; the same SQL "
    "views, runs on and exports. Work in this order: read the dataset (dataset_get), run on a few "
    "rows (LIMIT 20) with run_preview then run_start, look at the answers with sql_query, adjust "
    "the prompt or model, then run on all rows. To pick a model, run two or three on the same rows "
    "and columns_compare their columns, against labels you trust if there are any. Runs cost money "
    "and take time: tell the user the estimate before a run on all rows, and don't start another "
    "run on the same rows unless something changed. Failed answers can be asked again with "
    "run_resume; a changed prompt, options or model is a new run on the source dataset. The "
    "API does the same work, for scripts."
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
_ERRORS = (InvalidRequest, NotFound, Forbidden, Unauthorized, openrouter.OpenRouterError)


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
    def datasets_list() -> list[Dataset]:
        """Every dataset: rows, columns, what it was made from (parent_id, branch) and the run making
        it, if any. The starting point: find the dataset to work on, or see what a run made."""
        return datasets.list_datasets(_me().org.id)

    @tool
    def dataset_get(
        dataset_id: DatasetId,
        profile: Annotated[
            bool, Field(description="Also profile every column (slower on big datasets).")
        ] = False,
    ) -> DatasetDetail:
        """One dataset in full: columns with types, source, lineage and run. Read it before writing
        SQL or a prompt, so column names and types are right; profile it to know the values."""
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
        result lists the columns, so the next step is a prompt or a query."""
        me = _me("member")
        return datasets.create_dataset(me.org.id, source, connection_id)

    @tool
    def dataset_delete(dataset_id: DatasetId) -> None:
        """Delete a dataset and the run that made it; datasets made from it stay. Use it to clean
        up tries the user no longer needs, when they ask."""
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
    ) -> Comparison:
        """How often columns give the same value per row: models against each other, or against
        labels you trust, with each column's accuracy. Use it to pick a model or judge quality;
        every count comes with a `where` clause, to see those rows with sql_query."""
        me = _me()
        datasets.check_access(me.org.id, dataset_id)
        request = compare.CompareRequest(
            columns=columns,
            reference=reference,
            tolerance=tolerance,
            ignore_case=ignore_case,
            trim_whitespace=trim_whitespace,
            sql=sql,
        )
        return compare.compare(dataset_id, request)

    @tool
    def run_preview(
        dataset_id: DatasetId,
        tasks: Annotated[list[Task], Field(description="As for run_start.")],
        sql: Sql = ALL_ROWS,
    ) -> RunPreview:
        """What a run would do before it does: rows, calls, rough cost in USD, the prompt rendered
        for a few rows with warnings, and what stops it running. Catches a bad prompt or a
        surprise cost before money is spent: call it before every run_start, and tell the user the
        cost before a run on all rows."""
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
        """Ask every task of every model about the rows the SQL picks, making a new dataset with the
        answer columns added (`dataset_id` in the result). Start on a few rows (LIMIT 20), look,
        then run on all; the same prompt and model on a row already answered is free, anything
        changed is paid for. Small runs finish within `wait_seconds`; poll the rest with
        run_get."""
        me = _me("member")
        datasets.check_access(me.org.id, dataset_id)
        run = runs.create_run(
            dataset_id, RunRequest(sql=sql, tasks=tasks), me.user.id if me.user else None
        )
        return _wait(run, wait_seconds)

    @tool
    def run_get(run_id: str, wait_seconds: WaitSeconds = 0) -> Run:
        """A run's status, progress (`done` of `total` calls), cost and failed answers. Poll it
        while a run goes; its dataset's rows fill in meanwhile."""
        me = _me()
        runs.check_access(me.org.id, run_id)
        return _wait(runs.get_run(run_id), wait_seconds)

    @tool
    def run_stop(run_id: str) -> Run:
        """Stop a run after the calls in flight, e.g. when the first answers look wrong. run_resume
        continues it later, for free."""
        me = _me("member")
        runs.check_access(me.org.id, run_id)
        return runs.stop_run(run_id)

    @tool
    def run_resume(run_id: str, wait_seconds: WaitSeconds = 0) -> Run:
        """Continue a stopped or failed run, or ask a done run's failed answers again: what was
        answered stays answered, the rest is paid for. For a changed prompt, options or model,
        start a new run on the source dataset instead; a run's tasks are frozen."""
        me = _me("member")
        runs.check_access(me.org.id, run_id)
        return _wait(runs.resume_run(run_id), wait_seconds)

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
        file. The last step: hand the user the data with its answer columns, where they use it."""
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
    ) -> list[openrouter.Model]:
        """Models a task can use, with prices per token, cheapest first. Use it to pick a model by
        name or price; the defaults from task_types_get are fine to start with."""
        _me()
        found = openrouter.models()
        needle = search.lower()
        return [
            m
            for m in found
            if (kind is None or m.kind == kind)
            and (needle in m.id.lower() or needle in m.name.lower())
        ]

    return mcp


def _wait(run: Run, seconds: int) -> Run:
    """The run as it stands once done, or after `seconds`."""
    until = time.monotonic() + seconds
    while run.status in runs.ACTIVE and time.monotonic() < until:
        time.sleep(0.5)
        run = runs.get_run(run.id)
    return run
