"""Measure TUI key-response latency through tmux: send a key, poll the pane
until the content changes, report elapsed wall time."""

import subprocess
import sys
import time

TARGET = "qsql-demo:stress"


def capture() -> str:
    return subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", TARGET],
        capture_output=True, text=True,
    ).stdout


def send(key: str) -> None:
    subprocess.run(["tmux", "send-keys", "-t", TARGET, key], check=True)


def probe(key: str, label: str, timeout: float = 30.0) -> float:
    before = capture()
    t0 = time.perf_counter()
    send(key)
    while time.perf_counter() - t0 < timeout:
        if capture() != before:
            dt = time.perf_counter() - t0
            print(f"{label:<42} {dt * 1000:8.0f} ms")
            return dt
        time.sleep(0.02)
    print(f"{label:<42}  TIMEOUT (> {timeout}s, no visible change)")
    return timeout


if __name__ == "__main__":
    for key, label in [a.split("=", 1) for a in sys.argv[1:]]:
        probe(key, label)
