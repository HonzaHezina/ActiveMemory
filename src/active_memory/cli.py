import argparse
import hashlib
import json
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    initialize = sub.add_parser("init")
    initialize.add_argument("--client", default="owner")
    initialize.add_argument("--permissions", default="read,write,admin")
    initialize.add_argument("--output", default="config/clients.json")
    args = parser.parse_args()
    if args.command == "init":
        permissions = args.permissions.split(",")
        if not set(permissions) <= {"read", "write", "admin"}:
            parser.error("unknown permission")
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        clients = json.loads(path.read_text()) if path.exists() else []
        if any(c["id"] == args.client for c in clients):
            parser.error("client already exists; rotate the key explicitly")
        key = secrets.token_urlsafe(32)
        clients.append(
            {
                "id": args.client,
                "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                "permissions": permissions,
            }
        )
        path.write_text(json.dumps(clients, indent=2) + "\n")
        print(f"Client: {args.client}\nBearer key (save securely): {key}")
        return
    import uvicorn

    from .api import create_app
    from .settings import Settings

    settings = Settings()
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port, workers=1, access_log=False
    )  # avoid leaking source identifiers in request logs


if __name__ == "__main__":
    main()
