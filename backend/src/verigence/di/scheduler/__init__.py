"""scheduler/ — EOD Retry Scheduler package.

Entry point:
    from verigence.di.scheduler.beat import get_eod_scheduler, EODRetryScheduler
"""
from verigence.di.scheduler.beat import EODRetryScheduler, get_eod_scheduler

__all__ = ["EODRetryScheduler", "get_eod_scheduler"]
