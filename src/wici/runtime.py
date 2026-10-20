"""Lifetime resources: instance lock and bounded local logs."""
import fcntl
import logging
from datetime import date, timedelta
from logging.handlers import TimedRotatingFileHandler


class _FIRMSSecretFilter(logging.Filter):
    def __init__(self, key):
        super().__init__()
        self.key = key

    def filter(self, record):
        message = record.getMessage()
        if self.key in message:
            record.msg = message.replace(self.key, '[REDACTED]')
            record.args = ()
        return True


def redact_firms_logs(key):
    """HTTPX logs full request URLs; FIRMS embeds its credential in the path."""
    if not key:
        return
    logger = logging.getLogger('httpx')
    if not any(isinstance(f, _FIRMSSecretFilter) and f.key == key for f in logger.filters):
        logger.addFilter(_FIRMSSecretFilter(key))


class InstanceLock:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / 'instance.lockfile').open('a+')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('Inna instancja korzysta już z tej bazy. Zatrzymaj ją przez Ctrl+C.') from None

    def close(self):
        fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()

def configure_logs(directory):
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('wici')
    logger.setLevel(logging.INFO)
    cutoff = date.today() - timedelta(days=13)
    for archived in directory.glob('app.log.*'):
        try:
            archived_date = date.fromisoformat(archived.name.removeprefix('app.log.'))
        except ValueError:
            continue
        if archived_date < cutoff:
            archived.unlink()
    handler = TimedRotatingFileHandler(directory / 'app.log', when='midnight', backupCount=13, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    return handler
