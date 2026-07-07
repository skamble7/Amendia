# app/logging_conf.py
import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter(LOG_FORMAT))

root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(handler)
