"""Lancement de yt-dlp / gallery-dl / ffmpeg en sous-processus.

Ils tournent en processus séparés plutôt qu'importés : une mise à jour
automatique de yt-dlp prend effet immédiatement, sans redémarrer le serveur.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Awaitable, Callable

from .config import settings

PYTHON = sys.executable


def js_runtimes() -> list[str]:
    """Runtimes JavaScript disponibles (YouTube en exige un depuis fin 2025)."""
    # yt-dlp les retrouve lui-même dans le PATH ; on ne passe que le nom
    # (un chemin Windows "C:\\..." contiendrait un ":" ambigu)
    return [name for name in ("deno", "node", "bun") if shutil.which(name)]


@contextmanager
def cookies_copy():
    """Copie temporaire du cookies.txt : yt-dlp réécrit le fichier qu'on lui donne,
    et plusieurs processus en parallèle pourraient le corrompre."""
    if not settings.cookies_file or not settings.cookies_file.is_file():
        yield None
        return
    fd, path = tempfile.mkstemp(prefix="cookies-", suffix=".txt", dir=_tmp_root())
    os.close(fd)
    try:
        shutil.copyfile(settings.cookies_file, path)
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _tmp_root() -> str:
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    return str(settings.temp_dir)


def ytdlp_base_args(cookies: str | None, warnings: bool = False) -> list[str]:
    args = [
        PYTHON, "-m", "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-cache-dir",
        "--socket-timeout", "20",
        "--retries", "3",
        "--extractor-retries", "3",
    ]
    if not warnings:
        args.append("--no-warnings")
    runtimes = js_runtimes()
    if runtimes:
        args.append("--no-js-runtimes")
        for rt in runtimes:
            args += ["--js-runtimes", rt]
    if cookies:
        args += ["--cookies", cookies]
    elif settings.cookies_from_browser:
        args += ["--cookies-from-browser", settings.cookies_from_browser]
    if settings.proxy:
        args += ["--proxy", settings.proxy]
    if settings.pot_provider_url:
        args += ["--extractor-args", f"youtubepot-bgutilhttp:base_url={settings.pot_provider_url}"]
    extra = os.environ.get("YTDLP_EXTRA_ARGS")
    if extra:
        import shlex
        args += shlex.split(extra)
    return args


def gallerydl_base_args(cookies: str | None) -> list[str]:
    args = [PYTHON, "-m", "gallery_dl", "--config-ignore"]
    if cookies:
        args += ["--cookies", cookies]
    elif settings.cookies_from_browser:
        args += ["--cookies-from-browser", settings.cookies_from_browser]
    if settings.proxy:
        args += ["-o", f"proxy={settings.proxy}"]
    return args


class ProcessResult:
    def __init__(self, returncode: int, stdout: str, stderr: str, timed_out: bool = False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


async def run(cmd: list[str], timeout: float, on_stdout_line: Callable[[str], Awaitable[None] | None] | None = None,
              cwd: str | None = None) -> ProcessResult:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUNBUFFERED"] = "1"
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL, cwd=cwd, env=env, limit=64 * 1024 * 1024,
    )
    out_chunks: list[str] = []

    async def read_stdout():
        assert proc.stdout
        if on_stdout_line is None:
            data = await proc.stdout.read()
            out_chunks.append(data.decode("utf-8", "replace"))
            return
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace")
            out_chunks.append(text)
            res = on_stdout_line(text.rstrip("\r\n"))
            if asyncio.iscoroutine(res):
                await res

    async def read_stderr():
        assert proc.stderr
        data = await proc.stderr.read()
        return data.decode("utf-8", "replace")

    try:
        _, stderr = await asyncio.wait_for(asyncio.gather(read_stdout(), read_stderr()), timeout)
        await proc.wait()
        return ProcessResult(proc.returncode or 0, "".join(out_chunks), stderr)
    except asyncio.TimeoutError:
        _kill(proc)
        await proc.wait()
        return ProcessResult(-1, "".join(out_chunks), "timed out", timed_out=True)
    except asyncio.CancelledError:
        _kill(proc)
        raise


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


async def ffmpeg(args: list[str], timeout: float = 600) -> ProcessResult:
    return await run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], timeout)


async def ffprobe_streams(path: Path) -> list[dict]:
    import json
    res = await run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], 60)
    if not res.ok:
        return []
    try:
        return json.loads(res.stdout).get("streams", [])
    except ValueError:
        return []


def package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None
