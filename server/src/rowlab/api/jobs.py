from fastapi import APIRouter

from rowlab.core import jobs
from rowlab.core.jobs import Job, JobConfig

router = APIRouter(tags=["jobs"])


@router.get("/v1/datasets/{dataset_id}/jobs", operation_id="listJobs")
def list_jobs(dataset_id: str) -> list[Job]:
    return jobs.list_jobs(dataset_id)


@router.post("/v1/datasets/{dataset_id}/jobs", operation_id="createJob", status_code=201)
def create_job(dataset_id: str, config: JobConfig) -> Job:
    return jobs.create_job(dataset_id, config)


@router.put("/v1/jobs/{job_id}", operation_id="updateJob")
def update_job(job_id: str, config: JobConfig) -> Job:
    return jobs.update_job(job_id, config)
