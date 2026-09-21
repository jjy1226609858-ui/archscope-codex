from __future__ import annotations

import argparse
import logging

import uvicorn

from archscope.paths import default_registry_path
from archscope.service.api import create_app
from archscope.service.application import ArchScopeApplication


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local ArchScope workbench")
    parser.add_argument("--registry", default=str(default_registry_path()))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="warning")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    application = ArchScopeApplication(args.registry)
    app = create_app(application, default_project_id=args.project_id)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()

