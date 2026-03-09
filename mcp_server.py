# -*- coding: utf-8 -*-
import os
import sys
import argparse
from typing import Any, Callable, Dict, List, Optional
from contextlib import redirect_stdout
import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.middleware.cors import CORSMiddleware

import uvicorn
from mcp.server.fastmcp import FastMCP

# ===== 你的工程内模块（保持不变）=====
from tools.run_terminal_command import run_terminal_command
from tools.rw_file import read_file, write_to_file
from tools.web_search import web_search
# from config.proj_dir import PROJECT_DIR

# os.makedirs(PROJECT_DIR, exist_ok=True)


def build_mcp_server() -> FastMCP:
    """
    构建 FastMCP server，并暴露 tools。
    注意：
    - Streamable HTTP 下建议 json_response=True（便于调试/互操作）
    - 工具内部 stdout 重定向到 stderr，避免污染可能的输出通道
    """
    mcp = FastMCP("fc-agent-tools", json_response=True)

    def _call_safely(fn: Callable[..., Any], **kwargs: Any) -> Any:
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

    return mcp


def build_asgi_app(mcp: FastMCP, allow_cors: bool = True) -> Starlette:
    """
    按官方文档：用 mcp.streamable_http_app() 挂载到 ASGI
    默认 Streamable HTTP path 是 /mcp（客户端连接 http://host:port/mcp）
    """
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        # 官方推荐：Streamable HTTP 模式下要让 session_manager 跑在 lifespan 里
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )

    if allow_cors:
        # 浏览器/跨域需要暴露 Mcp-Session-Id
        app = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id"],
        )

    return app


def main() -> None:
    # parser = argparse.ArgumentParser()
    # parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    # parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8000")))
    # parser.add_argument("--no-cors", action="store_true", help="关闭 CORS（仅本地/非浏览器客户端可用）")
    # args = parser.parse_args()

    # mcp = build_mcp_server()
    # app = build_asgi_app(mcp, allow_cors=(not args.no_cors))

    # print(f"[mcp-server] streamable-http serving at http://{args.host}:{args.port}/mcp", flush=True)
    # uvicorn.run(app, host=args.host, port=args.port)

    MCP_HOST = "0.0.0.0"
    MCP_PORT = 8001
    mcp = build_mcp_server()
    app = build_asgi_app(mcp, allow_cors=True)
    print(f"[mcp-server] streamable-http serving at http://{MCP_HOST}:{MCP_PORT}/mcp", flush=True)
    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    main()
