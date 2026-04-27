import logging
import os
from datetime import date


def setup_logger(name: str = "vibefinder", log_dir: str = "logs") -> logging.Logger:
    """Configure and return a logger with file (DEBUG) and console (WARNING) handlers."""
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured in this process

    logger.setLevel(logging.DEBUG)

    log_file = os.path.join(log_dir, f"{date.today().isoformat()}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
