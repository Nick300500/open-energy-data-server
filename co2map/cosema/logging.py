import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler


def get_handlers(log_path):
    # check of log_path exists
    if not os.path.exists("logs/"):
        # create log_path folder
        os.makedirs("logs/")

    # Create handlers
    c_handler = logging.StreamHandler(sys.stdout)
    # Was hardcoded to ERROR -- meant `docker compose logs` (which only sees
    # stdout/stderr) never showed the logger.info() calls that confirm a
    # scheduled run actually succeeded ("Scheduler starts at...", "Operation
    # sucessfull"), only the file handler below did (inside the container,
    # not visible to `docker compose logs`). Now configurable via LOG_LEVEL
    # (see compose.yml's co2map service, already set to INFO there) --
    # defaults to INFO, not ERROR, since that's what you actually want to see
    # by default in a containerized deployment.
    c_handler.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    c_format = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
    c_handler.setFormatter(c_format)

    f_handler = TimedRotatingFileHandler(log_path, when="W1", backupCount=2)
    f_handler.setLevel(logging.INFO)
    f_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    f_handler.setFormatter(f_format)

    return [f_handler, c_handler]
