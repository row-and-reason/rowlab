from fastapi import APIRouter

from rowlab.api.auth import CanEdit, CanRead
from rowlab.core import datasets, runs
from rowlab.core.runs import Estimate, Run, RunRequest

router = APIRouter(tags=["runs"])


@router.post("/v1/datasets/{dataset_id}/runs", operation_id="createRun", status_code=201)
def create_run(dataset_id: str, request: RunRequest, me: CanEdit) -> Run:
    """Queue a run of every task with every model on the rows the query picks (all rows by
    default). It adds each task's answers to the dataset as columns, `<column>__<model>`, which fill
    in as the run works through the rows in the background: poll `GET /v1/runs/{id}`.

    It asks only for answers the dataset doesn't have yet, and skips rows missing a value the prompt
    uses. So a run on all rows after a try on a few pays only for the rest; to ask what a stopped or
    failed run is still missing, resume it (`POST /v1/runs/{id}/resume`). A column name keeps its
    question: a different prompt, options or answer type under a name in use is refused.

    A task needs only its `template` and `type`; the result column and models default to ones that
    suit the type (see `GET /v1/utils/task-types`)."""
    datasets.check_access(me.org.id, dataset_id)
    return runs.create_run(dataset_id, request, me.user.id if me.user else None)


@router.get("/v1/datasets/{dataset_id}/runs", operation_id="listRuns")
def list_runs(dataset_id: str, me: CanRead) -> list[Run]:
    """The dataset's runs, newest first."""
    datasets.check_access(me.org.id, dataset_id)
    return runs.list_runs(dataset_id)


@router.post("/v1/datasets/{dataset_id}/estimate", operation_id="estimateRun")
def estimate_run(dataset_id: str, request: RunRequest, me: CanEdit) -> Estimate:
    """What `POST /v1/datasets/{id}/runs` with the same body would ask for and roughly cost, and why
    it can't run as it is, if so. Nothing is asked."""
    datasets.check_access(me.org.id, dataset_id)
    return runs.estimate(dataset_id, request)


@router.get("/v1/runs/{run_id}", operation_id="getRun")
def get_run(run_id: str, me: CanRead) -> Run:
    runs.check_access(me.org.id, run_id)
    return runs.get_run(run_id)


@router.post("/v1/runs/{run_id}/stop", operation_id="stopRun")
def stop_run(run_id: str, me: CanEdit) -> Run:
    """Stop after the calls in flight. Resuming it asks for what it didn't get to; answers it paid
    for are free."""
    runs.check_access(me.org.id, run_id)
    return runs.stop_run(run_id)


@router.post("/v1/runs/{run_id}/resume", operation_id="resumeRun", status_code=201)
def resume_run(run_id: str, me: CanEdit) -> Run:
    """Start an ended run again, as a new run whose `resumes` is this one: it asks what this one
    didn't get, the answers it didn't get to and those that failed, on the rows its query picks.
    Replies it paid for are free. Only the latest attempt can be resumed."""
    runs.check_access(me.org.id, run_id)
    return runs.resume_run(run_id, me.user.id if me.user else None)
