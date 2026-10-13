"""Import the NORMALIZED JSONL format; not a vendor-export parser."""

import argparse
import json
import os

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--url", default=os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8080"))
    args = parser.parse_args()
    key = os.environ.get("MEMORY_CLIENT_API_KEY")
    if not key:
        parser.error("MEMORY_CLIENT_API_KEY required")
    with httpx.Client(
        base_url=args.url, headers={"Authorization": f"Bearer {key}"}, timeout=120
    ) as client:
        with open(args.file, encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                response = client.post("/v1/episodes", json=json.loads(line))
                if not response.is_success:
                    raise SystemExit(
                        f"Import stopped at line {line_number}: HTTP {response.status_code}"
                    )
                body = response.json()
                print(
                    json.dumps(
                        {
                            "line": line_number,
                            "episode_id": body["episode_id"],
                            "duplicate": body["duplicate"],
                        }
                    )
                )


if __name__ == "__main__":
    main()
