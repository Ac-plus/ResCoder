import os, json

# 将 user_path 安全地约束到 base_dir 下：
# 允许 "index.html" / "src\\a.js" 这种相对路径
# 禁止 base_dir 之外 (例如 C:\\Windows\\... 或 ..\\..)
def _safe_join(base_dir: str, user_path: str) -> str:
    user_path = (user_path or "").strip().lstrip("/\\")
    full = os.path.abspath(os.path.join(base_dir, user_path))
    base = os.path.abspath(base_dir)
    if not (full == base or full.startswith(base + os.sep)):
        raise ValueError("不可访问指定目录之外的路径：{0}".format(full))
    return full

# 读取指定目录下的文本文件（路径相对 PROJECT_DIR）
def read_file(file_path: str) -> str:
    full_path = file_path # _safe_join(PROJECT_DIR, file_path)
    if not os.path.exists(full_path):
        return json.dumps({"ok": False, "error": "File not found", "file_path": file_path}, ensure_ascii=False)
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    return json.dumps({"ok": True, "file_path": file_path, "content": content}, ensure_ascii=False)

# 写入指定目录下的文本文件（路径相对 PROJECT_DIR）
def write_to_file(file_path: str, content: str) -> str:
    full_path = file_path # _safe_join(PROJECT_DIR, file_path)
    print("[write_to_file日志] file_path = " , file_path)
    parent = os.path.dirname(full_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Function Calling 参数本身就是 JSON 字符串，\n 会自然存在；无需 replace("\\n","\n")
    data = content if content is not None else ""
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(data)

    return json.dumps({"ok": True, "file_path": file_path, "bytes": len(data.encode("utf-8"))}, ensure_ascii=False)
