import asyncio
import codecs
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .brokers import ProviderError
from .config import Config

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def terminate(process: subprocess.Popen):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def process_options():
    return (
        {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )


class Runtime:
    def __init__(self, config: Config, db=None):
        self.config = config
        self.db = db
        self.jobs = {}
        self.lock = threading.Lock()

    def _save_auth_home(self, relative):
        self.config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.config.data_dir / f".codex-shared-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps({"home": relative}), encoding="utf-8")
        temporary.replace(self.config.data_dir / "codex-shared.json")

    def auth_home(self):
        """One administrator-managed Codex identity; research workspaces remain per user."""
        marker = self.config.data_dir / "codex-shared.json"
        with self.lock:
            if marker.exists():
                try:
                    relative = json.loads(marker.read_text(encoding="utf-8"))["home"]
                except (ValueError, KeyError, TypeError):
                    raise ProviderError("codex_shared_config_invalid") from None
                if not isinstance(relative, str) or not re.fullmatch(r"shared/codex|users/[0-9]+/codex", relative):
                    raise ProviderError("codex_shared_config_invalid")
                path = (self.config.data_dir / relative).resolve()
                if not path.is_relative_to(self.config.data_dir.resolve()):
                    raise ProviderError("codex_shared_config_invalid")
            else:
                relative = "shared/codex"
                path = self.config.data_dir / relative
                # Adopt an existing administrator login once, without copying or returning its tokens.
                if not (path / "auth.json").exists() and self.db:
                    for administrator in self.db.all(
                        "SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY id"
                    ):
                        candidate = self.config.data_dir / "users" / str(administrator["id"]) / "codex"
                        if (
                            candidate.resolve().is_relative_to(self.config.data_dir.resolve())
                            and (candidate / "auth.json").is_file()
                        ):
                            relative, path = f"users/{administrator['id']}/codex", candidate
                            break
                self._save_auth_home(relative)
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            return path

    def select_shared_login(self):
        with self.lock:
            self._save_auth_home("shared/codex")

    def clear_model_cache(self):
        if self.db:
            self.db.execute("DELETE FROM cache WHERE kind='models_codex'")

    def home(self, uid: int):
        path = self.config.data_dir / "users" / str(uid)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for child in ("codex", "workspace", "tmp"):
            (path / child).mkdir(exist_ok=True, mode=0o700)
        return path

    def env(self, uid: int):
        home = self.home(uid)
        allowed = {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "LANG",
            "LC_ALL",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        }
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "CODEX_HOME": str(self.auth_home()),
                "TMP": str(home / "tmp"),
                "TEMP": str(home / "tmp"),
                "TMPDIR": str(home / "tmp"),
                "NO_COLOR": "1",
                "PYTHONIOENCODING": "utf-8",
                "npm_config_cache": str(self.config.runtime / "npm-cache"),
                "npm_config_registry": "https://registry.npmjs.org",
            }
        )
        return env

    def codex(self) -> list[str]:
        # Resolve a JS entrypoint instead of executing user-controlled arguments through a Windows .cmd shim.
        candidates = [
            self.config.runtime / "node_modules/@openai/codex/bin/codex.js",
            Path("/opt/peat-runtime/node_modules/@openai/codex/bin/codex.js"),
        ]
        marker = self.config.runtime / "codex-active.json"
        if marker.exists():
            active = Path(json.loads(marker.read_text())["path"]).resolve()
            if active.is_relative_to(self.config.runtime.resolve()):
                candidates.insert(0, active / "node_modules/@openai/codex/bin/codex.js")
        executable = shutil.which("codex") or shutil.which("codex.cmd")
        if executable:
            candidates.append(Path(executable).parent / "node_modules/@openai/codex/bin/codex.js")
        for path in candidates:
            if path.is_file() and shutil.which("node"):
                return [shutil.which("node"), str(path)]
        if executable and Path(executable).suffix.lower() not in {".cmd", ".bat", ".ps1"}:
            return [executable]
        raise ProviderError("codex_not_installed")

    def run(
        self,
        uid: int,
        args: list[str],
        timeout=20,
        input_text: str | None = None,
        cancellation: threading.Event | None = None,
    ):
        if cancellation and cancellation.is_set():
            raise ProviderError("analysis_cancelled")
        process = subprocess.Popen(
            args,
            cwd=self.home(uid) / "workspace",
            env=self.env(uid),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **process_options(),
        )
        finished = threading.Event()

        def watch_cancellation():
            while not finished.wait(0.1):
                if cancellation.is_set():
                    terminate(process)
                    return

        if cancellation:
            threading.Thread(target=watch_cancellation, daemon=True).start()
        try:
            stdout, stderr = process.communicate(input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate(process)
            process.communicate()
            raise ProviderError("process_timeout") from None
        finally:
            finished.set()
        return process.returncode, stdout, stderr

    async def run_cancellable(self, uid: int, args: list[str], input_text: str):
        cancellation = threading.Event()
        worker = asyncio.create_task(asyncio.to_thread(self.run, uid, args, None, input_text, cancellation))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancellation.set()
            try:
                await asyncio.shield(worker)
            except (ProviderError, OSError):
                pass
            raise

    def start_job(self, uid: int, kind: str, args: list[str], timeout=120, on_success=None):
        with self.lock:
            if any(
                (job["uid"] == uid or kind in {"update", "login"})
                and job["kind"] == kind
                and job["status"] == "running"
                for job in self.jobs.values()
            ):
                raise ProviderError("job_already_running")
            # Retain recent results only; terminal output never goes into the SQLite database.
            expired = [
                key
                for key, job in self.jobs.items()
                if job["status"] != "running" and time.time() - job["started"] > 3600
            ]
            for key in expired:
                self.jobs.pop(key, None)
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "uid": uid,
                "kind": kind,
                "status": "running",
                "output": "",
                "started": time.time(),
                "exit_code": None,
            }
            self.jobs[job_id] = job

        def worker():
            process = None
            try:
                process = subprocess.Popen(
                    args,
                    cwd=self.home(uid) / "workspace",
                    env=self.env(uid),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    **process_options(),
                )
                job["process"] = process
                timer = threading.Timer(timeout, lambda: terminate(process))
                timer.start()
                try:
                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    # Read single bytes so device codes are available before login completes.
                    while chunk := process.stdout.read(1):
                        job["output"] = (job["output"] + decoder.decode(chunk))[-65536:]
                    process.wait()
                finally:
                    timer.cancel()
                if process.returncode == 0 and on_success:
                    on_success()
                job["exit_code"] = process.returncode
                job["status"] = "completed" if process.returncode == 0 else "failed"
            except (OSError, ProviderError):
                job.update(status="failed", output="process_start_failed")
            finally:
                if process:
                    terminate(process)
                job.pop("process", None)

        threading.Thread(target=worker, daemon=True).start()
        return job_id

    def job(self, uid: int, job_id: str):
        job = self.jobs.get(job_id)
        if not job or job["uid"] != uid:
            raise ProviderError("job_not_found")
        output = ANSI.sub("", job["output"])
        result = {key: job[key] for key in ("id", "kind", "status", "exit_code")}
        if job["kind"] == "login":
            # Return only public verification details, never CLI diagnostics or credential material.
            urls = re.findall(r"https://auth\.openai\.com/[a-zA-Z0-9/_-]+", output)
            codes = re.findall(r"\b[A-Z0-9]{4,6}-[A-Z0-9]{4,6}\b", output)
            result.update(
                {"verification_url": urls[0] if urls else None, "user_code": codes[0] if codes else None}
            )
        else:
            result["output"] = output
        return result

    def login(self, uid: int):
        command = self.codex() + ["login", "--device-auth", "-c", 'cli_auth_credentials_store="file"']
        self.select_shared_login()
        return self.start_job(
            uid,
            "login",
            command,
            900,
            self.clear_model_cache,
        )

    def login_status(self, uid: int):
        code, stdout, stderr = self.run(uid, self.codex() + ["login", "status"], timeout=15)
        return {"logged_in": code == 0}

    def models(self, uid: int):
        proc = subprocess.Popen(
            self.codex() + ["app-server"],
            cwd=self.home(uid) / "workspace",
            env=self.env(uid),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **process_options(),
        )
        messages = queue.Queue()

        def read():
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    pass
            messages.put(None)

        threading.Thread(target=read, daemon=True).start()

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def request(request_id, method, params):
            send({"id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if message is None:
                    break
                if message.get("id") == request_id:
                    if "error" in message:
                        raise ProviderError("codex_models_unavailable")
                    return message["result"]
            raise ProviderError("codex_models_unavailable")

        try:
            request(0, "initialize", {"clientInfo": {"name": "peat", "title": "Peat", "version": "0.1.0"}})
            send({"method": "initialized", "params": {}})
            models, cursor = [], None
            for request_id in range(1, 11):
                response = request(
                    request_id, "model/list", {"limit": 100, "includeHidden": False, "cursor": cursor}
                )
                for model in response.get("data", []):
                    models.append(
                        {
                            "id": model.get("model") or model["id"],
                            "name": model.get("displayName", model["id"]),
                            "efforts": [
                                item["reasoningEffort"] for item in model.get("supportedReasoningEfforts", [])
                            ],
                            "default_effort": model.get("defaultReasoningEffort", "auto"),
                        }
                    )
                cursor = response.get("nextCursor")
                if not cursor:
                    break
            return models
        finally:
            terminate(proc)
            proc.wait(timeout=5)

    def update_codex(self, uid: int, version: str):
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?", version):
            raise ProviderError("invalid_version")
        self.config.runtime.mkdir(parents=True, exist_ok=True)
        prefix = self.config.runtime / "codex-versions" / version
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            raise ProviderError("npm_not_installed")
        npm_js = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        command = [shutil.which("node"), str(npm_js)] if npm_js.exists() else [npm]

        def activate():
            entry = prefix / "node_modules/@openai/codex/bin/codex.js"
            code, output, _ = self.run(uid, [shutil.which("node"), str(entry), "--version"])
            if code or version not in output:
                raise ProviderError("runtime_validation_failed")
            self.activate_version("codex", prefix)

        return self.start_job(
            uid,
            "update",
            command
            + [
                "install",
                "--prefix",
                str(prefix),
                "--registry=https://registry.npmjs.org",
                "--no-audit",
                "--no-fund",
                "--ignore-scripts",
                f"@openai/codex@{version}",
            ],
            300,
            activate,
        )

    def activate_version(self, package: str, path: Path):
        temp = self.config.runtime / f"{package}-active.tmp"
        temp.write_text(json.dumps({"path": str(path.resolve())}), encoding="utf-8")
        temp.replace(self.config.runtime / f"{package}-active.json")

    def update_calendar(self, uid: int, version: str):
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ProviderError("invalid_version")
        prefix = self.config.runtime / "calendar-versions" / version
        prefix.mkdir(parents=True, exist_ok=True)

        def activate():
            if not (prefix / "exchange_calendars").is_dir():
                raise ProviderError("runtime_validation_failed")
            self.activate_version("calendar", prefix)

        return self.start_job(
            uid,
            "update",
            [
                sys.executable,
                "-m",
                "pip",
                "--isolated",
                "install",
                "--no-cache-dir",
                "--index-url",
                "https://pypi.org/simple",
                "--only-binary=:all:",
                "--upgrade",
                "--target",
                str(prefix),
                f"exchange-calendars=={version}",
            ],
            300,
            activate,
        )

    def shutdown(self):
        for job in list(self.jobs.values()):
            if job.get("process"):
                terminate(job["process"])
