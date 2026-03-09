# 📚 1.目录介绍
```
- config/               # 各种参数信息
    - api_keys.py       # 大模型/网络搜索API key
    - model_name.py     # 大模型名称
    - proj_dir.py       # 工作目录
    - system_prompt.py  # 系统提示词
    - task.py           # 用户需求（用户提示词）
- tools/
    - toolList.py       # 工具列表（兼容OpenAI接口的JSON）
    - rw_file.py        # 读写文件两个tool的实现
    - ...               # 其他不赘述，反正就是各种工具的实现
- rag/      
    - embed_models/     # **请将embedding模型下载到此处**
    - docs/             # 保存知识库文档，目前拥有两个子知识库（如下）
        - FAQ/
        - Standards/
    - index/            # 建立索引的脚本会将faiss索引保存到此处
    - rag_build.py      # 建立索引的脚本。**知识库有变动的话需要重新离线运行一次。**
    - retrieve.py       # 召回函数的定义&实现，client可以调用
    - download.py       # 用来下载bge-small-zh-v1.5的备用脚本。如果丢失了embedding模型可运行以下载
- outputs/              
    - ...               # 各个工作目录（snake, test, test2, ...）
- agent_fc.py           # [S2.1]FC架构的agent主代码
- agent_mcp.py          # [不建议使用]MCP架构的agent主代码（使用单文件自动运行server subprocess方式）
- mcp_server.py         # [S2.2.1][S2.2.2]MCP-CS架构的S端
- mcp_client.py         # [S2.2.1][S2.2.2]MCP-CS架构的C端
- mcp_scheduler.py      # [S2.2.1]自动化控制执行3个client
- README.md             # 本指南
```

# 🏃‍ 2.运行方法

- 可使用Function Calling**或**MCP方法进行运行。**其中只有2.2.1支持RAG。**
- 无论如何，首先均需要在`./config`目录下，确认你的`TASK_1`和`PROJ_DIR`。
- `API_KEY`等其他参数一般不用改（如果它们均可用）。

## 2.1 Function Calling
进入agent目录，运行：
```
python3 agent_fc.py
```

## 2.2 MCP

现已不支持原策略1。对于策略2（C-S模型），现在分为单agent和多agent流水线两种执行方法。

### 2.2.1 多Agent协同
设计了3个agent--coder、reviwer和tester。通过`mcp_scheduler.py`调度。对于用户提出的coding任务，自动串行执行这3个agent。

`mcp_scheduler.py`会自动执行下列命令：
```
# 通过系统/用户提示词区分每个子agent的具体需求
# SYSTEM_PROMPT_1,2,3分别表示coder、reviwer和tester所需的提示词
# TASK_1,2,3分别表示coder、reviwer和tester所需的用户需求
python mcp_client.py --system-prompt SYSTEM_PROMPT_1 --task TASK_1
python mcp_client.py --system-prompt SYSTEM_PROMPT_2 --task TASK_2
python mcp_client.py --system-prompt SYSTEM_PROMPT_3 --task TASK_3
```

每个子agent的**第1个**round都会执行RAG检索，将知识库里匹配到的chunks一同发给LLM。

#### **具体运行方法**

首先启动MCP server：
```
python mcp_server.py # 已删除：--host 0.0.0.0 --port 8001
```

新起一个终端运行调度器：
```
MCP_URL=http://127.0.0.1:8001/mcp python mcp_scheduler.py
```

运行日志会保存到工作目录的`scheduler_logs`子目录下。

### 2.2.2 单Agent

你也可以仍然使用老办法，只用一个agent控制全部的业务需求（代码生成+三级校验）。

#### **具体运行方法**

首先启动MCP server：
```
python mcp_server.py # 已删除：--host 0.0.0.0 --port 8001
```

然后新终端启动client（agent）：
```
# 运行前，一定要确认SYSTEM_PROMPT引用正确，以及--task输入的是TASK_1
MCP_URL="http://127.0.0.1:8001/mcp" python mcp_client.py --system-prompt SYSTEM_PROMPT --task TASK_1
```

此模式现在**支持**启动server后修改`TASK_1`和`PROJECT_DIR`，即不同client的请求会写到各自对应的工作目录下。