# import json, subprocess
# from config.proj_dir import PROJECT_DIR

# # 在工程目录下执行 shell 命令
# def run_terminal_command(command: str) -> str:
#     run_result = subprocess.run(
#         command,
#         shell=True,
#         cwd=PROJECT_DIR,
#         capture_output=True,
#         text=True
#     )
#     return json.dumps(
#         {
#             "ok": run_result.returncode == 0,
#             "command": command,
#             "returncode": run_result.returncode,
#             "stdout": run_result.stdout,
#             "stderr": run_result.stderr
#         },
#         ensure_ascii=False
#     )

import json
import os
import shlex
import subprocess
import sys
from typing import Optional
from config.proj_dir import PROJECT_DIR

def run_terminal_command(command: str, timeout_sec: int = 60) -> str:
    cmd = (command or "").strip()
    resolved_cmd = cmd

    # 1) 关键修复：把 "python ..." 固定为当前解释器 sys.executable
    #    解决 Windows 下 python 命令命中 Store alias / 其他 python / PATH 不一致 导致的卡死
    if cmd.lower().startswith("python "):
        script_part = cmd[len("python "):].strip()
        resolved_cmd = "\"{0}\" -u {1}".format(sys.executable, script_part)

    # 2) 额外修复：如果用户写 "py ..."（Windows launcher），也固定到 sys.executable
    elif cmd.lower().startswith("py "):
        script_part = cmd[len("py "):].strip()
        resolved_cmd = "\"{0}\" -u {1}".format(sys.executable, script_part)

    # 3) Windows 稳定性：避免弹窗/控制台相关副作用（可选，但建议加）
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW=0x08000000：避免某些环境下子进程拉起新窗口/行为异常
        creationflags = 0x08000000

    try:
        run_result = subprocess.run(
            resolved_cmd,
            shell=True,
            cwd="/root/agent/outputs", # PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            creationflags=creationflags,
        )
        return json.dumps(
            {
                "ok": run_result.returncode == 0,
                "command": cmd,
                "resolved_command": resolved_cmd,   # ✅ 新增：真实执行命令，便于排查
                "returncode": run_result.returncode,
                "stdout": run_result.stdout,
                "stderr": run_result.stderr,
            },
            ensure_ascii=False,
        )

    except subprocess.TimeoutExpired as e:
        # 4) 超时就返回（stdout/stderr 可能为 None）
        return json.dumps(
            {
                "ok": False,
                "command": cmd,
                "resolved_command": resolved_cmd,
                "returncode": None,
                "stdout": (e.stdout or ""),
                "stderr": (e.stderr or ""),
                "error": "timeout",
                "timeout_sec": timeout_sec,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "command": cmd,
                "resolved_command": resolved_cmd,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "error": "exception",
                "exception": str(e),
            },
            ensure_ascii=False,
        )
