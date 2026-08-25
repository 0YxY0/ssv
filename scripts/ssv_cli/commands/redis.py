"""Docker Redis lifecycle commands."""

from __future__ import annotations

from argparse import Namespace

from ..config import load_runtime_config
from ..context import ProjectContext
from ..output import header
from ..services.compose import start_redis, stop_redis


def _settings(context: ProjectContext, args: Namespace):
    return load_runtime_config(
        context,
        path=getattr(args, "config", None),
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        db=getattr(args, "db", None),
        stream=getattr(args, "stream_key", None),
        group=getattr(args, "group", None),
    ).redis


def start(context: ProjectContext, args: Namespace) -> int:
    header("启动 Docker Redis")
    return start_redis(context, _settings(context, args))


def stop(context: ProjectContext, _args: Namespace) -> int:
    header("停止 Docker Redis")
    return stop_redis(context)
