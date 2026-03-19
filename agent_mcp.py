import json
import os
import platform
import subprocess
import sys
from typing import Callable, Dict, List, Any, Optional
from contextlib import redirect_stdout
from datetime import datetime
import difflib

# from dotenv import load_dotenv
from openai import OpenAI

from tools.toolList import TOOLS
from tools.run_terminal_command import run_terminal_command
from tools.rw_file import read_file, write_to_file
from tools.web_search import web_search
from config.api_keys import API_KEY
from config.proj_dir import PROJECT_DIR
from config.task import TASK_1
from config.model_name import MODEL_NAME
from config.system_prompt import SYSTEM_PROMPT

os.makedirs(PROJECT_DIR, exist_ok=True)

# MCP SERVER：把工具跑到“子进程”里（stdio / JSON-RPC）
def _mcp_server_main() -> None:
    from mcp.server.fastmcp import FastMCP  # pip install mcp

    mcp = FastMCP("fc-agent-tools")

    def _call_safely(fn: Callable[..., str], **kwargs: Any) -> str:
        with redirect_stdout(sys.stderr):
            return fn(**kwargs)

    @mcp.tool(name="read_file")
    def read_file_tool(file_path: str) -> str:
        return _call_safely(read_file, file_path=file_path)

    @mcp.tool(name="write_to_file")
    def write_to_file_tool(file_path: str, content: str) -> str:
        return _call_safely(write_to_file, file_path=file_path, content=content)

    @mcp.tool(name="run_terminal_command")
    def run_terminal_command_tool(command: str) -> str:
        return _call_safely(run_terminal_command, command=command)

    @mcp.tool(name="web_search")
    def web_search_tool(
        query: str,
        top_k: int = 6,
        recency_days: Optional[int] = None,
        domains: Optional[List[str]] = None,
    ) -> str:
        kwargs: Dict[str, Any] = {"query": query, "top_k": top_k}
        if recency_days is not None:
            kwargs["recency_days"] = recency_days
        if domains is not None:
            kwargs["domains"] = domains
        return _call_safely(web_search, **kwargs)

    mcp.run(transport="stdio")


# MCP CLIENT
class MCPStdioClient:
    def __init__(self, server_cmd: List[str], env: Optional[Dict[str, str]] = None):
        self._id = 0
        self.proc = subprocess.Popen(
            server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("无法创建 MCP stdio 管道。")
        self._initialize()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, obj: Dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _recv(self) -> Dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            err_preview = ""
            try:
                if self.proc.stderr is not None:
                    err_preview = self.proc.stderr.read()[:2000]
            except Exception:
                pass
            raise RuntimeError("MCP server stdout EOF，可能已退出。stderr预览：{0}".format(err_preview))
        try:
            return json.loads(line)
        except Exception as e:
            raise RuntimeError("MCP 响应不是合法 JSON：{0}\n原始行：{1}".format(str(e), line[:500]))

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rid = self._next_id()
        req: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        self._send(req)

        while True:
            resp = self._recv()
            if resp.get("id") == rid:
                return resp

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        req: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            req["params"] = params
        self._send(req)

    def _initialize(self) -> None:
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "fc-agent-client", "version": "1.0"},
        }
        resp = self._request("initialize", init_params)
        if "error" in resp:
            raise RuntimeError("MCP initialize 失败：{0}".format(resp["error"]))
        self._notify("notifications/initialized")

    def list_tools(self) -> List[Dict[str, Any]]:
        resp = self._request("tools/list", {})
        if "error" in resp:
            raise RuntimeError("tools/list 失败：{0}".format(resp["error"]))
        result = resp.get("result", {}) or {}
        return result.get("tools", []) or []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        resp = self._request("tools/call", {"name": name, "arguments": arguments})
        if "error" in resp:
            return json.dumps({"ok": False, "error": "MCP tools/call error", "detail": resp["error"]}, ensure_ascii=False)

        result = resp.get("result", {}) or {}

        # 常见：{"content":[{"type":"text","text":"..."}], "isError":false}
        if isinstance(result, dict):
            if result.get("isError"):
                return json.dumps({"ok": False, "error": "Tool returned isError", "result": result}, ensure_ascii=False)

            content = result.get("content")
            if isinstance(content, list):
                texts: List[str] = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(str(item["text"]))
                    else:
                        texts.append(json.dumps(item, ensure_ascii=False))
                return "\n".join(texts)

            if isinstance(content, str):
                return content

        return json.dumps(result, ensure_ascii=False)

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2)
                except Exception:
                    self.proc.kill()
        except Exception:
            pass


# Function Calling Agent（工具执行层改为 MCP）
class FunctionCallingAgent:
    def __init__(self, model: str, api_key: str, project_directory: str, tools: List[Dict[str, Any]]):
        self.model = model
        self.project_directory = os.path.abspath(project_directory)
        self.tools_schema = tools

        self.client = OpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
        )

        self.fsm_state = "INIT"

        # ===== 启动 MCP server 子进程 =====
        env = os.environ.copy()
        env["PROJECT_DIR"] = self.project_directory

        server_cmd = [sys.executable, os.path.abspath(__file__), "--mcp-server"]
        self.mcp = MCPStdioClient(server_cmd=server_cmd, env=env)

        # 启动校验：列一下 server 端提供的 tools
        tool_list = self.mcp.list_tools()
        provided = sorted([t.get("name", "") for t in tool_list])
        print("- [mcp] server tools:", provided, flush=True)

    @staticmethod
    def get_operating_system_name() -> str:
        os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
        return os_map.get(platform.system(), "Unknown")

    @staticmethod
    def _stdin_is_interactive() -> bool:
        try:
            return sys.stdin.isatty()
        except Exception:
            return False

    def _tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        # tool_name 与 schema 一致，server 端也用同名暴露，无需映射
        return self.mcp.call_tool(tool_name, args)

    def close(self) -> None:
        if hasattr(self, "mcp") and self.mcp is not None:
            self.mcp.close()

    def run(self, user_input: str, max_rounds: int = 30, confirm_terminal: bool = True) -> str:
        try:
            file_list = ", ".join(
                os.path.relpath(os.path.join(self.project_directory, f), self.project_directory)
                for f in os.listdir(self.project_directory)
            )
        except Exception:
            file_list = ""

        system_msg = (
            SYSTEM_PROMPT.strip()
            + "\n\n"
            + "运行环境信息：\n"
            + "- OS: {0}\n".format(self.get_operating_system_name())
            + "- PROJECT_DIR: {0}\n".format(self.project_directory)
            + ("- Files: {0}\n".format(file_list) if file_list else "")
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_input},
        ]

        pre_write_snapshots: Dict[str, str] = {}

        for round_idx in range(1, max_rounds + 1):
            print("\n\n- [fc] round {0}/{1}: requesting model...".format(round_idx, max_rounds), flush=True)

            fsm_contract = {
                "当前FSM状态": self.fsm_state,
                "允许的FSM状态集合": ["INIT", "EXECUTE", "L1_CHECK", "L2_CHECK", "L3_CHECK", "ERROR_FIX", "SUCCESS"],
                "强制要求": (
                    "你每次回复给Agent时，必须在 message.content 中输出一个JSON对象（字符串形式），并至少包含以下字段：\n"
                    "1) fsm_state：你认为你本次回复时所处的FSM状态，必须属于“允许的FSM状态集合”。\n"
                    "2) note：一句话简短说明（可为空字符串）。\n"
                    "3) final_answer：仅在你认为任务已完成且不需要再调用任何工具时填写，否则可省略或置空。\n"
                ),
                "示例": {"fsm_state": "EXECUTE", "note": "准备调用工具读取文件", "final_answer": ""},
            }
            messages.append({"role": "system", "content": "【FSM协议】\n" + json.dumps(fsm_contract, ensure_ascii=False)})

            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools_schema,
                tool_choice="auto",
            )
            msg = resp.choices[0].message

            parsed_fsm_state = None
            parsed_final_answer = None
            content_raw = msg.content if msg.content is not None else ""

            if content_raw.strip():
                try:
                    obj = json.loads(content_raw)
                    if isinstance(obj, dict):
                        parsed_fsm_state = obj.get("fsm_state")
                        parsed_final_answer = obj.get("final_answer")
                except Exception:
                    pass

            assistant_record: Dict[str, Any] = {"role": "assistant"}
            if msg.content is not None:
                assistant_record["content"] = msg.content
            if getattr(msg, "tool_calls", None):
                assistant_record["tool_calls"] = msg.tool_calls

            if parsed_fsm_state:
                assistant_record["fsm_state"] = parsed_fsm_state
                self.fsm_state = parsed_fsm_state
            else:
                assistant_record["fsm_state"] = self.fsm_state

            messages.append(assistant_record)

            print("- [fsm] llm_state(returned) = {0}".format(assistant_record.get("fsm_state")), flush=True)

            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                if parsed_final_answer is not None and str(parsed_final_answer).strip():
                    self.fsm_state = "SUCCESS"
                    return str(parsed_final_answer)
                if (msg.content is not None) and msg.content.strip():
                    self.fsm_state = "SUCCESS"
                    return msg.content

            print("\n\n- [fc] tool_calls: {0}".format(len(tool_calls)), flush=True)

            for tc in tool_calls:
                tool_name = tc.function.name
                raw_args = tc.function.arguments or "{}"

                try:
                    args = json.loads(raw_args)
                except Exception as e:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Invalid JSON arguments", "exception": str(e), "raw_args": raw_args},
                        ensure_ascii=False
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                    continue

                if confirm_terminal and tool_name == "run_terminal_command":
                    cmd = args.get("command", "")
                    print("\n\n🔧 Tool request: run_terminal_command({0})".format(repr(cmd)), flush=True)

                    if not self._stdin_is_interactive():
                        tool_out = json.dumps(
                            {"ok": False, "error": "Non-interactive stdin; auto-canceled", "command": cmd},
                            ensure_ascii=False
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                        continue

                    ok = input("\n是否继续执行该命令？（Y/N）").strip().lower()
                    if ok != "y":
                        tool_out = json.dumps(
                            {"ok": False, "error": "Canceled by user", "command": cmd},
                            ensure_ascii=False
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                        continue

                # ===== write_to_file 备份 + diff（读写也走 MCP，确保一致后端）=====
                if tool_name == "write_to_file":
                    target_path = args.get("file_path", "")
                    before_text = ""
                    try:
                        before_json = self._tool_call("read_file", {"file_path": target_path})
                        before_obj = json.loads(before_json) if before_json else {}
                        if isinstance(before_obj, dict) and before_obj.get("ok"):
                            before_text = before_obj.get("content", "")
                    except Exception:
                        pass

                    pre_write_snapshots[target_path] = before_text

                    if before_text:
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        bak_path = "{0}.bak_{1}".format(target_path, ts)
                        _ = self._tool_call("write_to_file", {"file_path": bak_path, "content": before_text})
                        print("- [diff] 已创建备份：{0}".format(bak_path), flush=True)

                print("\n\n🔧 Tool exec(MCP): {0}({1})".format(tool_name, raw_args), flush=True)
                try:
                    tool_out = self._tool_call(tool_name, args)
                except Exception as e:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Tool execution error", "tool_name": tool_name, "exception": str(e)},
                        ensure_ascii=False
                    )

                if tool_name == "write_to_file":
                    target_path = args.get("file_path", "")
                    before_text = pre_write_snapshots.get(target_path, "")
                    after_text = ""
                    try:
                        after_json = self._tool_call("read_file", {"file_path": target_path})
                        after_obj = json.loads(after_json) if after_json else {}
                        if isinstance(after_obj, dict) and after_obj.get("ok"):
                            after_text = after_obj.get("content", "")
                    except Exception:
                        pass

                    diff_lines = list(
                        difflib.unified_diff(
                            before_text.splitlines(True),
                            after_text.splitlines(True),
                            fromfile="before/{0}".format(target_path),
                            tofile="after/{0}".format(target_path),
                            lineterm=""
                        )
                    )
                    diff_text = "\n".join(diff_lines).strip()
                    if diff_text:
                        print("\n- [diff] 文件变更如下：\n{0}\n".format(diff_text), flush=True)
                    else:
                        print("- [diff] 未检测到内容差异（可能是写入内容相同）。", flush=True)

                print("\n\n🔍 Tool result (truncated): {0}".format(tool_out[:500] + ("..." if len(tool_out) > 500 else "")), flush=True)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})

        return "达到最大轮数仍未完成任务。你可以增大 max_rounds 或检查 system prompt 与工具返回格式。"


def main() -> None:
    project_dir = os.path.abspath(PROJECT_DIR)
    os.makedirs(project_dir, exist_ok=True)

    agent = FunctionCallingAgent(
        model=MODEL_NAME,
        api_key=API_KEY,
        project_directory=project_dir,
        tools=TOOLS,
    )

    try:
        print("\n\n- [fc] PROJECT_DIR = {0}".format(project_dir))
        print("\n\n- [fc] TASK = {0}".format(TASK_1))
        result = agent.run(user_input=TASK_1, max_rounds=30, confirm_terminal=True)
        print("\n\n✅ Final Answer:\n{0}".format(result))
    finally:
        agent.close()


if __name__ == "__main__":
    if "--mcp-server" in sys.argv:
        _mcp_server_main()
    else:
        main()
