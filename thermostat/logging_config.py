import os
import logging.handlers
from logging.config import dictConfig


def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "default"},
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": "thermostat.log",
                "maxBytes": 10000000,
                "backupCount": 3,
                "formatter": "default",
            },
        },
        "root": {"level": level, "handlers": ["console", "file"]},
    })
