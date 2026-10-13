"""Reference-mode backup. STOP the API first for graph/journal consistency."""

import argparse
import shutil
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    parser.add_argument("--data", default="data")
    parser.add_argument("--service-stopped", action="store_true", required=True)
    args = parser.parse_args()
    source = Path(args.data)
    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(source / "journal.sqlite3") as live:
        with sqlite3.connect(destination / "journal.sqlite3") as backup:
            live.backup(backup)
    if (source / "reference-graph.json").exists():
        shutil.copy2(source / "reference-graph.json", destination / "reference-graph.json")
    print(f"Reference backup created: {destination}")


if __name__ == "__main__":
    main()
