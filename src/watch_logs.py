# watch_logs.py
import io
import os
import sys
import time
from pathlib import Path
from typing import Dict, Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileMovedEvent

# ---- configure which files to watch ----
# C:\Users\htdun\AppData\Local\Programs\phBot Testing\Log
# FILES: Set[Path] = {Path(r"C:\logs\app.log"), Path(r"C:\logs\worker.log")}  # or {"./app.log","./worker.log"}

LOG_DIR = Path(r"C:\Users\htdun\AppData\Local\Programs\phBot Testing\Log")
# find all log/text files
FILES = {p for p in LOG_DIR.glob("*.log")} | {p for p in LOG_DIR.glob("*.txt")}

# ---------------------------------------

class TailState:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None
        self.pos = 0
        self._open_if_exists()

    def _open_if_exists(self):
        if self.fh:
            try:
                self.fh.close()
            except Exception:
                pass
            self.fh = None
        if self.path.exists():
            # buffering=1 for line-buffered text reading; errors replace prevents crashes on odd encodings
            self.fh = open(self.path, "r", encoding="utf-8", errors="replace", newline="")
            # seek to end initially (don’t re-emit old content)
            self.fh.seek(0, os.SEEK_END)
            self.pos = self.fh.tell()

    def read_new_lines(self):
        if not self.fh:
            return
        self.fh.seek(self.pos)
        for line in self.fh:
            yield line.rstrip("\n")
        self.pos = self.fh.tell()

    def reopen(self):
        self._open_if_exists()

    def handle_truncate_if_any(self):
        if self.fh:
            try:
                size = os.fstat(self.fh.fileno()).st_size
            except Exception:
                size = None
            if size is not None and self.pos > size:
                # file was truncated/rotated; start from beginning
                self.fh.seek(0)
                self.pos = 0

class MultiFileHandler(FileSystemEventHandler):
    def __init__(self, tails: Dict[Path, TailState], parents: Set[Path]):
        super().__init__()
        self.tails = tails
        self.parents = parents

    def _maybe_emit(self, path: Path):
        # If this path is one of the watched files, emit new lines
        tail = self.tails.get(path)
        if tail:
            tail.handle_truncate_if_any()
            for line in tail.read_new_lines():
                print(f"[{path.name}] {line}", flush=True)

    def on_created(self, event: FileCreatedEvent):
        p = Path(event.src_path)
        # new file could be a rotated one coming back with same name
        if p in self.tails:
            self.tails[p].reopen()
            self._maybe_emit(p)

    def on_modified(self, event: FileModifiedEvent):
        p = Path(event.src_path)
        if p in self.tails:
            self._maybe_emit(p)

    def on_moved(self, event: FileMovedEvent):
        src = Path(event.src_path)
        dest = Path(event.dest_path)
        # If a watched file was moved away (rotation), reopen the original path
        if src in self.tails:
            # The old handle points to the moved file; reopen the original path name
            self.tails[src].reopen()
        # If the destination is exactly one we watch (rare), reopen there as well
        if dest in self.tails:
            self.tails[dest].reopen()

def main():
    # normalize paths and build parent directory set
    files = {p.resolve() for p in FILES}
    parents = {p.parent for p in files}

    # init tail states
    tails = {p: TailState(p) for p in files}

    # start observers for each parent directory (one observer can do multiple, but splitting is fine)
    observer = Observer()
    handler = MultiFileHandler(tails, parents)
    for parent in parents:
        observer.schedule(handler, str(parent), recursive=False)

    observer.start()
    try:
        # also poll occasionally to catch truncations without modify events on some filesystems
        while True:
            for t in tails.values():
                t.handle_truncate_if_any()
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    if not FILES:
        print("Configure FILES set at top of file.", file=sys.stderr)
        sys.exit(1)
    main()
