"""Pool de processus yt-dlp chauds (voir ytworker.py)."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os

from .config import settings
from .tools import PYTHON, ProcessResult

log = logging.getLogger("saphir.workers")


class _Worker:
    def __init__(self, generation: int):
        self.generation = generation
        self.proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = await asyncio.create_subprocess_exec(
            PYTHON, "-m", "app.ytworker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            limit=256 * 1024 * 1024,
        )
        line = await asyncio.wait_for(self.proc.stdout.readline(), 60)
        if not line or not json.loads(line).get("ready"):
            raise RuntimeError("worker yt-dlp: démarrage impossible")

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def call(self, req_id: int, args: list[str], timeout: float, **extra) -> dict:
        assert self.proc and self.proc.stdin and self.proc.stdout
        self.proc.stdin.write((json.dumps({"id": req_id, "args": args, **extra}) + "\n").encode())
        await self.proc.stdin.drain()
        line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        if not line:
            raise RuntimeError("worker yt-dlp arrêté")
        return json.loads(line)

    def kill(self) -> None:
        if self.alive:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass


class WorkerPool:
    def __init__(self, size: int):
        self.size = size
        self.generation = 0
        self._idle: asyncio.Queue[_Worker] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ids = itertools.count(1)

    def _queue(self) -> asyncio.Queue:
        # file et processus sont liés à la boucle asyncio qui les a créés
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self.shutdown()
            self._idle, self._loop = None, loop
        if self._idle is None:
            self._idle = asyncio.Queue()
            for _ in range(self.size):
                self._idle.put_nowait(_Worker(self.generation))
        return self._idle

    async def warm_up(self) -> None:
        """Démarre les workers en avance pour que la 1re analyse soit rapide."""
        queue = self._queue()
        workers = [queue.get_nowait() for _ in range(queue.qsize())]
        await asyncio.gather(*(self._ensure(w) for w in workers), return_exceptions=True)
        for w in workers:
            queue.put_nowait(w)

    async def _ensure(self, worker: _Worker) -> _Worker:
        if worker.generation != self.generation or not worker.alive:
            worker.kill()
            worker.generation = self.generation
            await worker.start()
        return worker

    def recycle(self) -> None:
        """Après une mise à jour de yt-dlp : les workers redémarrent à leur prochain usage."""
        self.generation += 1

    async def extract(self, args: list[str], timeout: float) -> tuple[dict | None, ProcessResult]:
        queue = self._queue()
        worker = await queue.get()
        try:
            await self._ensure(worker)
            res = await worker.call(next(self._ids), args, timeout)
            stderr = res.get("stderr") or ""
            if res.get("ok"):
                return res.get("info"), ProcessResult(0, "", stderr)
            return None, ProcessResult(1, "", stderr)
        except asyncio.TimeoutError:
            worker.kill()
            return None, ProcessResult(-1, "", "timed out", timed_out=True)
        except Exception as exc:
            log.warning("worker yt-dlp en échec : %s", exc)
            worker.kill()
            return None, ProcessResult(1, "", f"ERROR: {exc}")
        finally:
            queue.put_nowait(worker)

    async def aclose(self) -> None:
        """Arrêt propre, dans la boucle asyncio encore active."""
        if self._idle is None:
            return
        workers = []
        while not self._idle.empty():
            workers.append(self._idle.get_nowait())
        for w in workers:
            w.kill()
        await asyncio.gather(*(w.proc.wait() for w in workers if w.proc), return_exceptions=True)
        self._idle = None
        self._loop = None

    async def select_formats(self, info: dict, args: list[str], timeout: float = 20) -> list[dict] | None:
        """Formats que yt-dlp choisirait pour ces options (URL + en-têtes), sans rien télécharger."""
        queue = self._queue()
        worker = await queue.get()
        try:
            await self._ensure(worker)
            res = await worker.call(next(self._ids), args, timeout, op="select", info=info)
            return res.get("formats") if res.get("ok") else None
        except Exception as exc:
            log.warning("sélection de format impossible : %s", exc)
            worker.kill()
            return None
        finally:
            queue.put_nowait(worker)

    def shutdown(self) -> None:
        if self._idle is None:
            return
        while not self._idle.empty():
            self._idle.get_nowait().kill()


pool = WorkerPool(settings.extract_workers) if settings.extract_workers > 0 else None
