from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery('jusclipit', broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_routes = {
    'app.workers.tasks.process_video_job': {'queue': 'video-processing'},
    'app.workers.tasks.reset_pro_monthly_quotas': {'queue': 'maintenance'},
}
celery_app.conf.beat_schedule = {
    'reset-pro-monthly-quotas-daily': {
        'task': 'app.workers.tasks.reset_pro_monthly_quotas',
        'schedule': crontab(hour=0, minute=5),
    }
}
