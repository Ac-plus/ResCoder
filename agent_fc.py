import json
import os
import platform
import subprocess
import sys
import time
from typing import Callable, Dict, List, Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

import difflib
from datetime import datetime
from contextlib import redirect_stdout

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


class FunctionCallingAgent:
    def __init__(self, model: str, api_key: str, project_directory: str, tools: List[Dict[str, Any]]):
        self.model = model
        self.project_directory = os.path.abspath(project_directory)
        self.tools_schema = tools

        # 将“工具名 -> python 函数”映射起来（必须与 schema 的 name 一致）
        self.tools_impl: Dict[str, Callable[..., str]] = {
            "read_file": read_file,
            "write_to_file": write_to_file,
            "run_terminal_command": run_terminal_command,
            "web_search": web_search,
        }

        self.client = OpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
        )

        # ===== ✅ FSM：最小实现（仅满足：告知状态 + 回传状态 + 写入消息结构）=====
        self.fsm_state = "INIT"

    @staticmethod
    def get_api_key_from_env() -> str:
        load_dotenv()
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("未找到 DEEPSEEK_API_KEY（或 OPENROUTER_API_KEY）环境变量，请在 .env 中设置。")
        return api_key

    @staticmethod
    def get_operating_system_name() -> str:
        os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
        return os_map.get(platform.system(), "Unknown")

    def run(self, user_input: str, max_rounds: int = 30, confirm_terminal: bool = True) -> str:
        """
        - max_rounds: 防止无限循环
        - confirm_terminal: 是否对 run_terminal_command 做人工确认
        """
        # 你可以把工程文件列表也放进 system prompt（可选）
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

        for round_idx in range(1, max_rounds + 1):
            print("\n\n- [fc] round {0}/{1}: requesting model...".format(round_idx, max_rounds))

            # ===== ✅ FSM：每轮请求模型前，明确告知当前状态，并要求模型在 content(JSON) 中回传 fsm_state =====
            fsm_contract = {
                "当前FSM状态": self.fsm_state,
                "允许的FSM状态集合": ["INIT", "EXECUTE", "L1_CHECK", "L2_CHECK", "L3_CHECK", "ERROR_FIX", "SUCCESS"],
                "强制要求": (
                    "你每次回复给Agent时，必须在 message.content 中输出一个JSON对象（字符串形式），并至少包含以下字段：\n"
                    "1) fsm_state：你认为你本次回复时所处的FSM状态，必须属于“允许的FSM状态集合”。\n"
                    "2) note：一句话简短说明（可为空字符串）。\n"
                    "3) final_answer：仅在你认为任务已完成且不需要再调用任何工具时填写，否则可省略或置空。\n\n"
                    "注意：\n"
                    "- 你仍然可以像平常一样发起 tool_calls（函数调用）。\n"
                    "- 即使你发起了 tool_calls，你的 message.content 仍然必须是上面要求的 JSON 字符串。\n"
                    "- 如果你要给出最终答案，请把最终答案文本放进 final_answer 字段。\n"
                ),
                "示例": {
                    "fsm_state": "EXECUTE",
                    "note": "准备调用工具读取文件",
                    "final_answer": ""
                }
            }
            messages.append({"role": "system", "content": "【FSM协议】\n" + json.dumps(fsm_contract, ensure_ascii=False)})

            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools_schema,
                tool_choice="auto",
            )
            msg = resp.choices[0].message

            # ===== ✅ FSM：解析模型 content(JSON) 中的 fsm_state / final_answer，并附加到原有消息结构中 =====
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
                    parsed_fsm_state = None
                    parsed_final_answer = None

            # 先把 assistant message 记录下来（包含可能的 tool_calls）
            assistant_record: Dict[str, Any] = {"role": "assistant"}
            if msg.content is not None:
                assistant_record["content"] = msg.content
            if getattr(msg, "tool_calls", None):
                assistant_record["tool_calls"] = msg.tool_calls

            # ✅ 把FSM状态附加进原有消息结构（你要求的“状态附在消息结构里一并传回”）
            if parsed_fsm_state:
                assistant_record["fsm_state"] = parsed_fsm_state
                self.fsm_state = parsed_fsm_state
            else:
                # 若模型没有按协议返回，则仍记录当前状态，方便排查
                assistant_record["fsm_state"] = self.fsm_state

            messages.append(assistant_record)
            # ✅ 打印本轮FSM状态回传情况
            print("- [fsm] agent_state(before) = {0}".format(fsm_contract["当前FSM状态"]))
            print("- [fsm] llm_state(returned) = {0}".format(assistant_record.get("fsm_state")))

            # 1) 如果模型没有 tool_calls：优先读取 structured final_answer，其次兼容旧行为
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                if parsed_final_answer is not None and str(parsed_final_answer).strip():
                    print("\n\n- [fc] model returned final answer (结构化final_answer).")
                    self.fsm_state = "SUCCESS"
                    return str(parsed_final_answer)

                if (msg.content is not None) and msg.content.strip():
                    print("\n\n- [fc] model returned final content.")
                    self.fsm_state = "SUCCESS"
                    return msg.content

            # 2) 如果模型请求工具调用：逐个执行
            if tool_calls:
                print("\n\n- [fc] tool_calls: {0}".format(len(tool_calls)))

                for idx, tc in enumerate(tool_calls, 1):
                    tool_name = tc.function.name
                    raw_args = tc.function.arguments or "{}"
                    # 只预览前 200 字符，避免太长刷屏
                    preview = raw_args[:200] + ("..." if len(raw_args) > 200 else "")
                    print("- [fc] round {0}: tool_request {1}/{2}: {3}({4})"
                          .format(round_idx, idx, len(tool_calls), tool_name, preview),
                          flush=True)

            for tc in tool_calls:
                tool_name = tc.function.name
                raw_args = tc.function.arguments or "{}"

                # 解析 JSON 参数
                try:
                    args = json.loads(raw_args)
                    print("获取到此次工具调用的raw_args为：", raw_args)
                except Exception as e:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Invalid JSON arguments", "exception": str(e), "raw_args": raw_args},
                        ensure_ascii=False
                    )
                    print("出现Expection：", str(e))
                    print("无法获取模型给的raw_args！以下信息将被发回给模型：")
                    print({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                    continue

                # 工具存在性检查
                if tool_name not in self.tools_impl:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Unknown tool", "tool_name": tool_name},
                        ensure_ascii=False
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                    print("模型请求了不存在的工具！以下信息将被发回给模型：")
                    print({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                    continue

                # 可选：对终端命令做人工确认
                if confirm_terminal and tool_name == "run_terminal_command":
                    cmd = args.get("command", "")
                    print("\n\n🔧 Tool request: run_terminal_command({0})".format(repr(cmd)))
                    ok = input("\n是否继续执行该命令？（Y/N）").strip().lower()
                    if ok != "y":
                        tool_out = json.dumps(
                            {"ok": False, "error": "Canceled by user", "command": cmd},
                            ensure_ascii=False
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})
                        print("\n\n- [fc] command canceled by user.")
                        continue

                # 执行工具
                print("\n\n🔧 Tool exec: {0}({1})".format(tool_name, raw_args))
                try:
                    tool_out = self.tools_impl[tool_name](**args)
                except Exception as e:
                    tool_out = json.dumps(
                        {"ok": False, "error": "Tool execution error", "tool_name": tool_name, "exception": str(e)},
                        ensure_ascii=False
                    )

                print("\n\n🔍 Tool result (truncated): {0}".format(tool_out[:500] + ("..." if len(tool_out) > 500 else "")))

                # 将工具结果以 role="tool" 回传，并绑定 tool_call_id
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_out})

            # 继续下一轮，让模型根据工具结果决定下一步
            print("\n\n- [fc] round {0}: tool results appended, continue...".format(round_idx))

        # 超出轮数仍未结束
        return "达到最大轮数仍未完成任务。你可以增大 max_rounds 或检查 system prompt 与工具返回格式。"


def main():
    global PROJECT_DIR
    PROJECT_DIR = os.path.abspath(PROJECT_DIR)

    api_key = API_KEY
    agent = FunctionCallingAgent(
        model=MODEL_NAME,
        api_key=api_key,
        project_directory=PROJECT_DIR,
        tools=TOOLS,
    )

    print("\n\n- [fc] PROJECT_DIR = {0}".format(PROJECT_DIR))
    print("\n\n- [fc] TASK = {0}".format(TASK_1))

    result = agent.run(
        user_input=TASK_1,
        max_rounds=30,
        confirm_terminal=True,  # 保留你原先对 run_terminal_command 的 Y/N 交互
    )
    print("\n\n✅ Final Answer:\n{0}".format(result))

main()