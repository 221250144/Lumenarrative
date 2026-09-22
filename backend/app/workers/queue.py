import logging
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import update
from celery import Celery
from app.config import settings
from app.models import SessionLocal, Job, AnalysisRun, EditVersion, Submission

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xuguangji")
celery_app = Celery("xuguangji", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def dispatch(job_id):
    try:
        if settings.queue_mode == "celery":
            celery_execute.delay(job_id)
        else:
            executor.submit(execute, job_id)
    except Exception:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            job.status, job.error_code, job.error_message = (
                "failed",
                "QUEUE_UNAVAILABLE",
                "后台队列不可用，请启动 Redis 和 worker 后重试",
            )
            db.commit()


@celery_app.task(name="xuguangji.execute")
def celery_execute(job_id):
    execute(job_id)


def execute(job_id):
    with SessionLocal() as db:
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running")
        )
        db.commit()
        if not claimed.rowcount:
            return
        job = db.get(Job, job_id)

    def progress(stage, completed, total):
        with SessionLocal() as db:
            row = db.get(Job, job_id)
            row.stage, row.completed_units, row.total_units = stage, completed, total
            db.commit()

    try:
        from app.workflows.pipeline import (
            process_asset,
            analyze,
            verify_submission,
            render_edit,
        )

        handlers = {
            "preprocess": process_asset,
            "analysis": analyze,
            "verification": verify_submission,
            "render": render_edit,
        }
        handlers[job.type](job, progress)
        with SessionLocal() as db:
            row = db.get(Job, job_id)
            row.status = "succeeded"
            db.commit()
    except Exception as exc:
        logging.getLogger("xuguangji.jobs").exception("Job %s failed", job_id)
        with SessionLocal() as db:
            row = db.get(Job, job_id)
            row.status, row.error_code, row.error_message = (
                "failed",
                "PROCESSING_FAILED",
                str(exc)[:1000],
            )
            for key, cls, attr in [
                ("analysis_id", AnalysisRun, "status"),
                ("edit_id", EditVersion, "render_status"),
                ("submission_id", Submission, "verification_status"),
            ]:
                if key in job.data:
                    entity = db.get(cls, job.data[key])
                    if entity:
                        setattr(entity, attr, "failed")
            db.commit()
