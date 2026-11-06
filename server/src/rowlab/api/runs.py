from fastapi import APIRouter

from rowlab.core import runs
from rowlab.core.runs import Run, RunSummary

router = APIRouter(tags=["runs"])


@router.post("/v1/jobs/{job_id}/runs", operation_id="createRun", status_code=201)
def create_run(job_id: str) -> Run:
    """Start running every task with every model on the rows in the job's scope. It runs in the
    background: poll `GET /v1/runs/{id}` for its progress and answers. Answers already given are
    free: they come from the response cache."""
    return runs.create_run(job_id)


@router.get("/v1/datasets/{dataset_id}/runs", operation_id="listRuns")
def list_runs(dataset_id: str) -> list[RunSummary]:
    """A dataset's runs, newest first, without their answers."""
    return runs.list_runs(dataset_id)


@router.get("/v1/runs/{run_id}", operation_id="getRun")
def get_run(run_id: str) -> Run:
    """A run with its settings, costs and answers for every row."""
    return runs.get_run(run_id)
