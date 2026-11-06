"""Small picklable parser fixtures; child imports do not load the API/test suite."""

import time


def hanging_parser(file_bytes, filename):
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(0.01)
    return "finished"


def slow_parser(file_bytes, filename):
    time.sleep(0.35)
    return "parsed slow resume text"


def allocate_too_much(file_bytes, filename):
    return str(len(bytearray(384 * 1024 * 1024)))
