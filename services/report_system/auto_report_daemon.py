import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from auto_report_once import run_once, setup_logging
from config import BASE_DIR
from notifier import notify_failure


def parse_hhmm(value):
    hour, minute = value.split(':', 1)
    return int(hour), int(minute)


def next_run_time(hhmm):
    hour, minute = parse_hhmm(hhmm)
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def make_once_args(report_type, send, retries, retry_interval, allow_latest):
    return SimpleNamespace(
        report_type=report_type,
        date=None,
        to='',
        cc='',
        send=send,
        force=False,
        no_update=False,
        allow_latest=allow_latest,
        resend=False,
        retries=retries,
        retry_interval=retry_interval,
    )


def parse_args():
    parser = argparse.ArgumentParser(description='24/7 futures report scheduler')
    parser.add_argument('--maintenance-time', default='06:20', help='Daily maintenance time HH:MM')
    parser.add_argument('--white-time', default='16:30', help='White-session report time HH:MM')
    parser.add_argument('--send', action='store_true', help='Actually send emails. Default is dry-run.')
    parser.add_argument('--white-retries', type=int, default=6)
    parser.add_argument('--white-retry-interval', type=int, default=10)
    parser.add_argument('--poll-seconds', type=int, default=30)
    return parser.parse_args()


def run_maintenance(logger):
    cmd = [sys.executable, str(BASE_DIR / 'maintenance.py')]
    logger.info(f'Run maintenance: {" ".join(cmd)}')
    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
        timeout=60 * 20,
    )
    if result.stdout:
        logger.info(result.stdout.strip())
    if result.stderr:
        logger.warning(result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f'maintenance.py failed with code {result.returncode}')
    return {'status': 'maintenance_done'}


def main():
    setup_logging()
    logger = logging.getLogger('auto_report')
    args = parse_args()

    jobs = [
        {
            'name': 'maintenance',
            'time': args.maintenance_time,
            'next': next_run_time(args.maintenance_time),
            'func': lambda: run_maintenance(logger),
        },
        {
            'name': 'white',
            'time': args.white_time,
            'next': next_run_time(args.white_time),
            'func': None,
            'once_args': make_once_args(
                report_type='white',
                send=args.send,
                retries=args.white_retries,
                retry_interval=args.white_retry_interval,
                allow_latest=False,
            ),
        },
    ]

    logger.info('Auto report daemon started.')
    for job in jobs:
        logger.info(f'Job {job["name"]}: {job["time"]}, next={job["next"].strftime("%Y-%m-%d %H:%M:%S")}')

    try:
        while True:
            now = datetime.now()
            for job in jobs:
                if now >= job['next']:
                    logger.info(f'Run job: {job["name"]}')
                    try:
                        if job.get('func'):
                            result = job['func']()
                        else:
                            result = run_once(job['once_args'])
                        logger.info(f'Job {job["name"]} result: {result["status"]}')
                    except Exception as exc:
                        logger.exception(f'Job {job["name"]} failed: {exc}')
                        notify_failure(
                            f'自动任务失败：{job["name"]}',
                            str(exc),
                            logger=logger,
                        )
                    job['next'] = next_run_time(job['time'])
                    logger.info(f'Next {job["name"]}: {job["next"].strftime("%Y-%m-%d %H:%M:%S")}')
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        logger.info('Auto report daemon stopped by user.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
