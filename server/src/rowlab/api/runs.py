from fastapi import APIRouter

from rowlab.core import runs
from rowlab.core.runs import Run

router = APIRouter(tags=["runs"])


@router.post("/v1/jobs/{job_id}/runs", operation_id="createRun", status_code=201)
def create_run(job_id: str) -> Run:
    """Queue a run of every task with every model on the rows in the job's scope. It makes a new
    dataset (`dataset_id`), created right away with every row; the answer columns of the rows in
    scope fill in as the run works through them in the background: poll `GET /v1/runs/{id}` for its
    progress. Answers already given are free: they come from the response cache."""
    return runs.create_run(job_id)


@router.get("/v1/runs/{run_id}", operation_id="getRun")
def get_run(run_id: str) -> Run:
    return runs.get_run(run_id)


@router.post("/v1/runs/{run_id}/stop", operation_id="stopRun")
def stop_run(run_id: str) -> Run:
    """Stop after the calls in flight. The chunk in progress is redone on resume, for free."""
    return runs.stop_run(run_id)


@router.post("/v1/runs/{run_id}/resume", operation_id="resumeRun")
def resume_run(run_id: str) -> Run:
    """Continue a stopped or failed run from its first unwritten chunk."""
    return runs.resume_run(run_id)
