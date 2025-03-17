import logging
import os
from dataclasses import dataclass
from enum import StrEnum, auto
from os import PathLike
from pathlib import Path
from typing import TypedDict

import httpx
import pytest

logger = logging.getLogger(__name__)

httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

PLUGIN_NAME = "httpdist"
ARTIFACTS_DIR = Path("./artifacts")


class RunsOn(TypedDict):
    tags: list[str]


NodeId = str
SessionId = str
WorkerId = str


class TestPhase(StrEnum):
    Setup = auto()
    Call = auto()
    Teardown = auto()


class TestSpec(TypedDict):
    nodeid: NodeId
    worker_requirements: list[RunsOn] | None


class Events:
    @dataclass
    class Start:
        hostname: str | None

    @dataclass
    class Finish:
        hostname: str | None

    @dataclass
    class Report:
        hostname: str | None
        nodeid: NodeId
        report: pytest.TestReport


class EndOfSession(Exception):
    pass


class ApiUsageError(Exception):
    pass


class SessionNotStartedError(ApiUsageError):
    pass


class NoWorkersAvailableError(ApiUsageError):
    pass


class BaseApi:
    API_URL = os.getenv("HTTPDIST_API_URL", "http://localhost:8000")
    session_id: SessionId | None = None

    def __init__(self, config: pytest.Config):
        self.config = config

    async def _apost(self, path: str, data: dict):
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.API_URL}/{path}", json=data)
            response.raise_for_status()
            return response.json()

    def _post_file(self, path: str, file_path: PathLike):
        file_path = Path(file_path)
        with httpx.Client() as client:
            with open(file_path, "rb") as f:
                response = client.post(f"{self.API_URL}/{path}", files={"env": f})
            response.raise_for_status()
            return response.json()

    async def _aget(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.API_URL}/{path}", params=params)
            response.raise_for_status()
            return response.json()

    async def _aget_raw(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.API_URL}/{path}", params=params)
            response.raise_for_status()
            return response

    def _get(self, path: str, params: dict | None = None):
        with httpx.Client() as client:
            response = client.get(f"{self.API_URL}/{path}", params=params)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, data: dict):
        with httpx.Client() as client:
            response = client.post(f"{self.API_URL}/{path}", json=data)
            response.raise_for_status()
            return response.json()
