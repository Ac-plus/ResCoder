# -*- coding: utf-8 -*-
import json
import os
import platform
import sys
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime
import difflib
import asyncio

from openai import OpenAI

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from tools.toolList import TOOLS
from config.api_keys import API_KEY
from config.proj_dir import PROJECT_DIR
from config.model_name import MODEL_NAME

import config.system_prompt as system_prompt_mod
import config.task as task_mod

os.makedirs(PROJECT_DIR, exist_ok=True)

from rag.retrieve import retrieve as rag_retrieve


class MCPStreamableHTTPClient:
    def __init__(self, url: str):
        self.url = url

    async def _with_session(self):
        async with streamable_http_client(self.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return session

    async def _list_tools_async(self) -> List[Dict[str, Any]]:
        async with streamable_http_client(self.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                res = await session.list_tools()
                out: List[Dict[str, Any]] = []
                for t in getattr(res, "tools", []) or []:
                    out.append(
                        {
                            "name": getattr(t, "name", ""),
                            "description": getattr(t, "description", "") or "",
                        }
                    )
                return out

    async def _call_tool_async(self, name: str, arguments: Dict[str, Any]) -> str:
        async with streamable_http_client(self.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)

                # 兼容 TextContent / 结构化输出
                if getattr(result, "content", None):
                    texts: List[str] = []
                    for item in result.content:
                        if isinstance(item, types.TextContent):
                            texts.append(item.text)
                        else:
                            # 非文本内容（图片/其它）做兜底序列化
                            try:
                                texts.append(json.dumps(item.model_dump(), ensure_ascii=False))
                            except Exception:
                                texts.append(str(item))
                    return "\n".join(texts)

                # 兜底：structuredContent
                sc = getattr(result, "structuredContent", None)
                if sc is not None:
                    try:
                        return json.dumps(sc, ensure_ascii=False)
                    except Exception:
                        return str(sc)

                return ""

    def list_tools(self) -> List[Dict[str, Any]]:
        return asyncio.run(self._list_tools_async())

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        return asyncio.run(self._call_tool_async(name, arguments))

class FunctionCallingAgent:
    def __init__(
        self,
        model: str,
        api_key: str,
        project_directory: str,
        tools: List[Dict[str, Any]],
        mcp_url: str,
        system_prompt: str,
    ):
        self.model = model
        self.project_directory = os.path.abspath(project_directory)
        self.tools_schema = tools
        self.system_prompt = system_prompt

        self.client = OpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
        )

        self.mcp = MCPStreamableHTTPClient(mcp_url)

        tool_list = self.mcp.list_tools()
        provided = sorted([t.get("name", "") for t in tool_list])
        print("- [mcp-http] server tools:", provided, flush=True)

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

    # 修改tool调用的传参，拼接上工作目录
    # 对于run_terminal_command，拼接"cd ... &&"
    def _inject_project_dir(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        a = dict(args or {})
        proj = os.path.abspath(self.project_directory)

        if tool_name in ("read_file", "write_to_file"):
            fp = a.get("file_path", "")
            if isinstance(fp, str) and fp and (not os.path.isabs(fp)):
                a["file_path"] = os.path.join(proj, fp)

        if tool_name == "run_terminal_command":
            cmd = a.get("command", "")
            if isinstance(cmd, str) and cmd.strip():
                cmd_strip = cmd.lstrip()
                lowered = cmd_strip.lower()
                already_has_cd = lowered.startswith("cd ") or lowered.startswith("pushd ") or lowered.startswith("set-location ")
                if not already_has_cd:
                    if platform.system() == "Windows":
                        prefix = 'cd /d "{0}" && '.format(proj)
                    else:
                        prefix = 'cd "{0}" && '.format(proj)
                    a["command"] = prefix + cmd_strip

        return a

    def _tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        fixed_args = self._inject_project_dir(tool_name, args)
        print(fixed_args)
        return self.mcp.call_tool(tool_name, fixed_args)

    def run(self, user_input: str, max_rounds: int = 30, confirm_terminal: bool = True) -> str:
        try:
            file_list = ", ".join(
                os.path.relpath(os.path.join(self.project_directory, f), self.project_directory)
                for f in os.listdir(self.project_directory)
            )
        except Exception:
            file_list = ""

        system_msg = (
            self.system_prompt.strip()
            + "\n\n"
            + "运行环境信息：\n"
            + "- OS: {0}\n".format(self.get_operating_system_name())
            + "- PROJECT_DIR: {0}\n".format(self.project_directory)
            + ("- Files: {0}\n".format(file_list) if file_list else "")
        )

        # messages: List[Dict[str, Any]] = [
        #     {"role": "system", "content": system_msg},
        #     {"role": "user", "content": user_input},
        # ]
        ########
        try:
            rag = rag_retrieve(
                query=user_input,
                index_dir="/root/agent/rag/index",
                embed_model_dir="/root/agent/rag/embed_models/bge-small-zh-v1.5",
                top_n_per_lib=3,
                faiss_topk=20,
                w_bm25=0.5,
                w_vec=0.5,
                reuse_singleton=True,
            )
        except Exception as e:
            rag = {"FAQ": [], "Standards": []}
            print("- [rag] retrieve failed:", str(e), flush=True)

        def _format_hits(hits_by_lib):
            lines = []
            for lib in ("FAQ", "Standards"):
                hits = hits_by_lib.get(lib, []) or []
                lines.append("## %s" % lib)
                if not hits:
                    lines.append("(no hits)")
                    continue
                for i, h in enumerate(hits, 1):
                    src = h.get("source_relpath") or h.get("source_path") or ""
                    score = h.get("score", 0.0)
                    lines.append(
                        "- [{lib} #{i}] score={score:.4f} source={src} chunk_index={ci}\n{text}".format(
                            lib=lib, i=i, score=float(score), src=src, ci=h.get("chunk_index", -1), text=h.get("text", "")
                        )
                    )
            return "\n".join(lines).strip()

        rag_context = _format_hits(rag)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_msg},
            {"role": "system", "content": "以下为RAG召回到的执行规范（来自FAQ与Standards两个知识库），执行任务时要遵守这些内容。\n\n" + rag_context},
            {"role": "user", "content": user_input},
        ]

        pre_write_snapshots: Dict[str, str] = {}

        for round_idx in range(1, max_rounds + 1):
            print("\n\n- [mcp] round {0}/{1}: requesting model...".format(round_idx, max_rounds), flush=True)

            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools_schema,
                tool_choice="auto",
            )
            msg = resp.choices[0].message

            assistant_record: Dict[str, Any] = {"role": "assistant"}
            if msg.content is not None:
                assistant_record["content"] = msg.content
            if getattr(msg, "tool_calls", None):
                assistant_record["tool_calls"] = msg.tool_calls

            messages.append(assistant_record)

            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                if (msg.content is not None) and msg.content.strip():
                    return msg.content

            print("\n\n- [mcp] tool_calls: {0}".format(len(tool_calls)), flush=True)

            for tc in tool_calls:
                tool_name = tc.function.name
                raw_args = tc.function.arguments or "{}"

                try:
                    args = json.loads(raw_args)
                except Exception as e:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Invalid JSON arguments", "exception": str(e), "raw_args": raw_args},
                        ensure_ascii=False,
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                    continue

                if confirm_terminal and tool_name == "run_terminal_command":
                    cmd = args.get("command", "")
                    print("\n\n🔧 Tool request: run_terminal_command({0})".format(repr(cmd)), flush=True)

                    if not self._stdin_is_interactive():
                        tool_out = json.dumps(
                            {"ok": False, "error": "Non-interactive stdin; auto-canceled", "command": cmd},
                            ensure_ascii=False,
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                        continue

                    ok = input("\n是否继续执行该命令？（Y/N）").strip().lower()
                    if ok != "y":
                        tool_out = json.dumps(
                            {"ok": False, "error": "Canceled by user", "command": cmd},
                            ensure_ascii=False,
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                        continue

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

                print("\n\n🔧 Tool exec(MCP-HTTP): {0}({1})".format(tool_name, raw_args), flush=True)
                try:
                    tool_out = self._tool_call(tool_name, args)
                except Exception as e:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Tool execution error", "tool_name": tool_name, "exception": str(e)},
                        ensure_ascii=False,
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
                            lineterm="",
                        )
                    )
                    diff_text = "\n".join(diff_lines).strip()
                    if diff_text:
                        print("\n- [diff] 文件变更如下：\n{0}\n".format(diff_text), flush=True)
                    else:
                        print("- [diff] 未检测到内容差异（可能是写入内容相同）。", flush=True)

                print(
                    "\n\n🔍 Tool result (truncated): {0}".format(
                        tool_out[:500] + ("..." if len(tool_out) > 500 else "")
                    ),
                    flush=True,
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})

        return "达到最大轮数仍未完成任务。你可以增大 max_rounds 或检查 system prompt 与工具返回格式。"


def _load_attr(mod: Any, attr_name: str) -> str:
    if not hasattr(mod, attr_name):
        raise AttributeError("Module {0} has no attribute: {1}".format(getattr(mod, "__name__", "<?>"), attr_name))
    val = getattr(mod, attr_name)
    if not isinstance(val, str):
        raise TypeError("{0}.{1} must be str, got {2}".format(getattr(mod, "__name__", "<?>"), attr_name, type(val)))
    return val


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()

    SYSTEM_PROMPT = _load_attr(system_prompt_mod, args.system_prompt)
    TASK = _load_attr(task_mod, args.task)

    project_dir = os.path.abspath(PROJECT_DIR)
    os.makedirs(project_dir, exist_ok=True)

    # 默认按官方 /mcp 路径
    mcp_url = os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp")

    agent = FunctionCallingAgent(
        model=MODEL_NAME,
        api_key=API_KEY,
        project_directory=project_dir,
        tools=TOOLS,
        mcp_url=mcp_url,
        system_prompt=SYSTEM_PROMPT,
    )

    print("\n\n- [mcp] PROJECT_DIR = {0}".format(project_dir))
    print("\n\n- [mcp] SYSTEM_PROMPT = {0}".format(args.system_prompt))
    print("\n\n- [mcp] TASK = {0}".format(args.task))
    result = agent.run(user_input=TASK, max_rounds=40, confirm_terminal=True)
    print("\n\n✅ Final Answer:\n{0}".format(result))


if __name__ == "__main__":
    main()
