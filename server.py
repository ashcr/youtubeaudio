#!/usr/bin/env python3
"""Local YouTube saver. Uses yt-dlp on this machine. Binds to localhost only."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DOWNLOADS = ROOT / "downloads"
HOST = "127.0.0.1"
PORT = 8787

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def youtube_target(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw or len(raw) > 500 or any(c in raw for c in "\n\r\x00"):
        return None
    if VIDEO_ID.match(raw):
        return f"https://www.youtube.com/watch?v={raw}"
    if not raw.startswith(("http://", "https://")):
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None
    return raw


def search_query(value: str) -> str | None:
    text = " ".join((value or "").split())
    if not text or len(text) > 200:
        return None
    if youtube_target(text):
        return None
    return text


def thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def run_ytdlp(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["yt-dlp", "--no-update", "--no-warnings", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def search(query: str) -> list[dict]:
    result = run_ytdlp(
        ["ytsearch8:" + query, "--flat-playlist", "-J", "--no-playlist"],
        timeout=45,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Search failed").strip()[-400:])
    data = json.loads(result.stdout or "{}")
    items = []
    for entry in data.get("entries") or []:
        video_id = entry.get("id") or ""
        if not VIDEO_ID.match(video_id):
            continue
        duration = entry.get("duration")
        items.append(
            {
                "id": video_id,
                "title": entry.get("title") or "Untitled",
                "channel": entry.get("channel") or entry.get("uploader") or "",
                "duration": int(duration) if isinstance(duration, (int, float)) else None,
                "thumbnail": thumb(video_id),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    return items


def describe(url: str) -> dict:
    result = run_ytdlp(
        ["--skip-download", "--no-playlist", "-J", url],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Could not read that video").strip()[-400:])
    data = json.loads(result.stdout or "{}")
    video_id = data.get("id") or ""
    duration = data.get("duration")
    return {
        "id": video_id,
        "title": data.get("title") or "Untitled",
        "channel": data.get("channel") or data.get("uploader") or "",
        "duration": int(duration) if isinstance(duration, (int, float)) else None,
        "thumbnail": thumb(video_id) if VIDEO_ID.match(video_id) else "",
        "url": data.get("webpage_url") or url,
    }


def start_download(url: str, fmt: str) -> str:
    if fmt not in {"mp3", "mp4"}:
        raise ValueError("Choose mp3 or mp4")
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed")
    if fmt == "mp3" and shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to make an mp3")

    job_id = uuid.uuid4().hex[:12]
    folder = DOWNLOADS / job_id
    folder.mkdir(parents=True, exist_ok=True)
    job = {
        "id": job_id,
        "status": "running",
        "progress": "Starting",
        "error": "",
        "file": "",
        "filename": "",
    }
    with jobs_lock:
        jobs[job_id] = job

    threading.Thread(target=download_worker, args=(job, folder, url, fmt), daemon=True).start()
    return job_id


def download_worker(job: dict, folder: Path, url: str, fmt: str) -> None:
    template = str(folder / "%(title).180B.%(ext)s")
    if fmt == "mp3":
        args = [
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--embed-metadata",
        ]
    else:
        args = [
            "-f",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "--merge-output-format",
            "mp4",
        ]
    command = [
        "yt-dlp",
        "--no-update",
        "--no-playlist",
        "--restrict-filenames",
        "--newline",
        "-o",
        template,
        *args,
        url,
    ]
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.strip()
            if text:
                job["progress"] = text[-240:]
        code = proc.wait(timeout=900)
        if code != 0:
            job["status"] = "error"
            job["error"] = job["progress"] or "yt-dlp failed"
            return
        files = [p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".part")]
        if not files:
            job["status"] = "error"
            job["error"] = "yt-dlp finished without a file"
            return
        saved = max(files, key=lambda p: p.stat().st_mtime)
        job["file"] = str(saved)
        job["filename"] = saved.name
        job["status"] = "done"
        job["progress"] = "Ready"
    except Exception as exc:  # noqa: BLE001 - surface the worker failure to the UI
        job["status"] = "error"
        job["error"] = str(exc)[-400:]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print("[youtube-audio]", fmt % args)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/search":
            self.handle_search(parsed.query)
            return
        if parsed.path == "/api/info":
            self.handle_info(parsed.query)
            return
        if parsed.path.startswith("/api/jobs/"):
            self.handle_job(parsed.path)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/download":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length > 8000:
            self.send_json(413, {"error": "Request is too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Expected JSON"})
            return
        url = youtube_target(str(body.get("url") or ""))
        fmt = str(body.get("format") or "")
        if not url:
            self.send_json(400, {"error": "Paste a YouTube link"})
            return
        try:
            job_id = start_download(url, fmt)
        except (ValueError, RuntimeError) as exc:
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(202, {"id": job_id})

    def handle_search(self, query: str) -> None:
        params = parse_qs(query)
        text = search_query((params.get("q") or [""])[0])
        if not text:
            self.send_json(400, {"error": "Enter a title or artist"})
            return
        try:
            items = search(text)
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            self.send_json(502, {"error": str(exc)[-400:]})
            return
        self.send_json(200, {"items": items})

    def handle_info(self, query: str) -> None:
        params = parse_qs(query)
        url = youtube_target((params.get("url") or [""])[0])
        if not url:
            self.send_json(400, {"error": "That is not a YouTube link"})
            return
        try:
            info = describe(url)
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            self.send_json(502, {"error": str(exc)[-400:]})
            return
        self.send_json(200, info)

    def handle_job(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        # api / jobs / id [/ file]
        if len(parts) < 3:
            self.send_error(404)
            return
        job_id = parts[2]
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            self.send_json(404, {"error": "That save is gone. Start it again."})
            return
        if len(parts) == 4 and parts[3] == "file":
            self.send_file(job)
            return
        self.send_json(
            200,
            {
                "id": job["id"],
                "status": job["status"],
                "progress": job["progress"],
                "error": job["error"],
                "filename": job["filename"],
            },
        )

    def send_file(self, job: dict) -> None:
        if job["status"] != "done" or not job["file"]:
            self.send_json(409, {"error": "The file is not ready"})
            return
        path = Path(job["file"])
        if not path.is_file() or DOWNLOADS not in path.resolve().parents:
            self.send_json(404, {"error": "File missing"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    DOWNLOADS.mkdir(exist_ok=True)
    if shutil.which("yt-dlp") is None:
        raise SystemExit("Install yt-dlp first: brew install yt-dlp")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"YouTube Audio is running at http://{HOST}:{PORT}", flush=True)
    print(f"Saved files also stay in {DOWNLOADS}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
