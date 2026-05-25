import logging
import os
from datetime import datetime


class Logger:
    def __init__(self, name: str, log_dir: str = "logs"):
        log_dir = os.path.abspath(log_dir)
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(
            log_dir,
            f"{name}_{datetime.now().strftime('%Y-%m-%d')}.log"
        )

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            console_handler = logging.StreamHandler()

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    def info(self, message: str):
        self.logger.info(message)

    def error(self, message: str):
        self.logger.error(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def success(self, message: str):
        self.logger.info(f"✅ {message}")