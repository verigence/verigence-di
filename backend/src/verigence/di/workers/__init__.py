"""workers/ — Background processing worker package.

Entry points:
    from verigence.di.workers.processor import get_worker, ProcessingWorker
    from verigence.di.workers.job_runner import run_processing_job
"""
from verigence.di.workers.processor import ProcessingWorker, get_worker

__all__ = ["ProcessingWorker", "get_worker"]
