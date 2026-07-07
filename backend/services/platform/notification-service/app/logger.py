# app/logger.py
import logging, sys

def get_logger(name: str = "notification"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(h)
    return logger

# Export a module-level logger so `from app.logger import logger` works
logger = get_logger("notification-service")

__all__ = ["get_logger", "logger"]
