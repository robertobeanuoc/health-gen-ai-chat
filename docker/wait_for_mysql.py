#!/usr/bin/env python3
"""Blocks until the MySQL server accepts connections, then returns so the entrypoint can proceed.

Polls with a real PyMySQL connection (not just a TCP check) using the same
MYSQL_* env vars the app and dbt already read, so it only proceeds once MySQL
is actually ready to serve queries — not just listening on the port.
"""
import logging
import os
import sys
import time

import pymysql

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("wait_for_mysql")

MYSQL_HOST = os.environ.get("MYSQL_HOST", "mysql-server")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE")
POLL_INTERVAL_SECONDS = 5


def wait_for_mysql():
    logger.info(f"Waiting for MySQL ({MYSQL_HOST}:{MYSQL_PORT}) to be ready...")
    while True:
        try:
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                connect_timeout=5,
            )
            conn.close()
            logger.info("MySQL is ready, proceeding...")
            return
        except pymysql.MySQLError as exc:
            logger.warning(f"MySQL not reachable yet ({exc}), retrying...")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    wait_for_mysql()
    sys.exit(0)
