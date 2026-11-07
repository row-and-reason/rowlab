from fastapi import APIRouter

from rowlab.api.auth import CanEdit, CanRead
from rowlab.core import datasets, runs
from rowlab.core.runs import Estimate, Run, RunRequest

router = APIRouter(tags=["runs"])


@router.post("/v1/datasets/{dataset_id}/runs", operation_id="createRun", status_code=201)
def create_run(dataset_id: str, request: RunRequest, me: CanEdit) -> Run:
    """Queue a run of every task with every model on the rows in the scope (all rows if none is
    given). It makes a new dataset (`dataset_id`), created right away with every row; the answer
    columns of the rows in scope fill in as the run works through them in the background: poll
    `GET /v1/runs/{id}` for its progress. Answers already given are free: they come from the
    response cache.

    A task needs only its `template` and `type`; the result column and models default to ones that
    suit the type (see `GET /v1/utils/task-types`)."""
    datasets.check_access(me.org.id, dataset_id)
    return runs.create_run(dataset_id, request)


@router.post("/v1/datasets/{dataset_id}/estimate", operation_id="estimateRun")
def estimate_run(dataset_id: str, request: RunRequest, me: CanEdit) -> Estimate:
    """What `POST /v1/datasets/{id}/runs` with the same body would take and roughly cost, and why
    it can't run as it is, if so. Nothing is asked."""
    datasets.check_access(me.org.id, dataset_id)
    return runs.estimate(dataset_id, request)


@router.get("/v1/runs/{run_id}", operation_id="getRun")
def get_run(run_id: str, me: CanRead) -> Run:
    runs.check_access(me.org.id, run_id)
    return runs.get_run(run_id)


@router.post("/v1/runs/{run_id}/stop", operation_id="stopRun")
def stop_run(run_id: str, me: CanEdit) -> Run:
    """Stop after the calls in flight. The chunk in progress is redone on resume, for free."""
    runs.check_access(me.org.id, run_id)
    return runs.stop_run(run_id)


@router.post("/v1/runs/{run_id}/resume", operation_id="resumeRun")
def resume_run(run_id: str, me: CanEdit) -> Run:
    """Continue a stopped or failed run, or a done one with failed answers: its failed answers are
    asked again first, then it continues from its first unwritten chunk."""
    runs.check_access(me.org.id, run_id)
    return runs.resume_run(run_id)
