from fastapi import APIRouter

from rowlab.api.auth import CanEdit, CanRead
from rowlab.core import datasets, manual, runs
from rowlab.core.runs import Estimate, Run, RunRequest

router = APIRouter(tags=["runs"])


@router.post("/v1/datasets/{dataset_id}/runs", operation_id="createRun", status_code=201)
def create_run(dataset_id: str, request: RunRequest, me: CanEdit) -> Run:
    """Queue a run of every task with every model on the rows in the scope (all rows if none is
    given). It makes a new dataset (`dataset_id`), created right away with only the selected rows;
    the answer columns fill in as the run works through them in the background: poll
    `GET /v1/runs/{id}` for its progress. Answers already given to the same rows, by a run in the
    same dataset tree, are free: they are reused.

    With `method: "manual"` no model is asked and no provider key is needed: the run waits for
    answers (`PUT /v1/runs/{id}/tasks/{task_id}/answers`) in columns named after the tasks, without
    model suffixes, until `POST /v1/runs/{id}/finish`.

    A task needs only its `template` and `type`; the result column and models default to ones that
    suit the type (see `GET /v1/utils/task-types`)."""
    datasets.check_access(me.org.id, dataset_id)
    return runs.create_run(dataset_id, request, me.user.id if me.user else None)


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


@router.put("/v1/runs/{run_id}/tasks/{task_id}/answers", operation_id="saveManualAnswers")
def save_manual_answers(run_id: str, task_id: str, request: manual.Answers, me: CanEdit) -> Run:
    """Set labels on an open manual run. Null clears a label. Batches may span several saved parts;
    retry an interrupted batch with the same values. Concurrent edits use the last saved value.
    """
    runs.check_access(me.org.id, run_id)
    return manual.save(run_id, task_id, request)


@router.post("/v1/runs/{run_id}/finish", operation_id="finishManualRun")
def finish_manual_run(run_id: str, me: CanEdit) -> Run:
    """Finish manual labeling and freeze the output dataset. Unanswered cells stay null.
    Repeating this call returns the completed run. Labels can no longer be changed.
    """
    runs.check_access(me.org.id, run_id)
    return manual.finish(run_id)
