from rq import Queue
from redis import Redis

from app.core.config import settings


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.REDIS_URL)


def get_queue() -> Queue:
    return Queue(settings.JOB_QUEUE_NAME, connection=get_redis_connection())


def enqueue_job(job_id: str) -> str:
    queue = get_queue()
    rq_job = queue.enqueue("app.workers.tasks.run_job_task", job_id)
    return rq_job.id
