import os
import sys
import subprocess
from datetime import datetime

from config.proj_dir import PROJECT_DIR


def _ensure_dir(p: str) -> None:
    if not os.path.isdir(p):
        os.makedirs(p, exist_ok=True)


def _run_one(role: str, system_prompt_var: str, task_var: str, mcp_url: str, client_py: str, logs_dir: str) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(logs_dir, "{0}_{1}.log".format(role, ts))

    cmd = [
        sys.executable,
        client_py,
        "--system-prompt",
        system_prompt_var,
        "--task",
        task_var,
    ]

    env = dict(os.environ)
    env["MCP_URL"] = mcp_url

    header = "\n\n=== [{0}] start | system_prompt={1} task={2} | MCP_URL={3} ===\n".format(
        role, system_prompt_var, task_var, mcp_url
    )
    sys.stdout.write(header)
    sys.stdout.flush()

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.flush()

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            f.write(line)
            f.flush()

        rc = proc.wait()

    tail = "\n=== [{0}] end | returncode={1} | log={2} ===\n".format(role, rc, log_path)
    sys.stdout.write(tail)
    sys.stdout.flush()

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(tail)
        f.flush()

    return rc


def main() -> None:
    mcp_url = os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp")
    client_py = os.environ.get("MCP_CLIENT_PY", os.path.join(os.path.dirname(__file__), "mcp_client.py"))

    logs_dir = os.path.join(os.path.abspath(PROJECT_DIR), "scheduler_logs")
    _ensure_dir(logs_dir)

    plan = [
        ("coder", "SYSTEM_PROMPT_1", "TASK_1"),
        ("reviewer", "SYSTEM_PROMPT_2", "TASK_2"),
        ("tester", "SYSTEM_PROMPT_3", "TASK_3"),
    ]

    for role, sp, tk in plan:
        rc = _run_one(role, sp, tk, mcp_url, client_py, logs_dir)
        if rc != 0:
            sys.stderr.write("\n[Scheduler] stop: role={0} failed with returncode={1}\n".format(role, rc))
            sys.stderr.flush()
            sys.exit(rc)

    sys.stdout.write("\n[Scheduler] all done.\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
