import asyncio

from app.services.jobs.orchestrator import run_job_pipeline


def run_job_task(job_id: str) -> None:
    asyncio.run(run_job_pipeline(job_id))
