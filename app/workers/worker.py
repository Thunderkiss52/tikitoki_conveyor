from rq import Worker

from app.core.config import settings
from app.workers.queue import get_redis_connection


def main() -> None:
    connection = get_redis_connection()
    worker = Worker([settings.JOB_QUEUE_NAME], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
