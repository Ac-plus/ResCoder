# ResCoder-基于多Agent协同的科研代码助理

> 版本迭代记录

## v1

使用ReAct模式、Function Calling通信方法，实现了一个能自动生成可执行代码的Agent。Agent的执行逻辑如下。首先用户提出需求，Agent获取工具列表后发送给大模型。如下图：

<img width="1053" height="261" alt="image" src="https://github.com/user-attachments/assets/7cc8b774-8ef7-4e1b-aa3b-b994877992fd" />

接下来，会不断执行“LLM请求调用工具->Agent执行工具->向LLM反馈结果”的循环，直到LLM认为任务完成、已不需要调用工具为止。注意每轮Agent向LLM反馈结果时都会将可用的工具列表一并发出。如下图：

<img width="1224" height="298" alt="image" src="https://github.com/user-attachments/assets/962606aa-87ea-4bee-b81a-f990f4f36a27" />

当LLM认为任务已完成，则告知Agent，Agent结束此次任务。如下图：

<img width="766" height="149" alt="image" src="https://github.com/user-attachments/assets/1f2185d7-3f98-46f4-ae0a-a443c864a0bf" />

当前版本实现了以下功能：

- 根据用户需求生成代码与文档，并保存到指定位置
- 初步增量式开发（基于原有代码修改）
- 高敏感操作确认

当前版本包含3个Tools：

- `read_file`：读取文件内容
- `write_to_file`：写入文件
- `run_terminal_command`：运行终端命令

## v1.1

新增了功能：

- 可执行网络检索

Tools新增：

- `web_search`：使用API Key通道进行联网搜索

## v1.2

新增了功能：

- 可进行三级校验，确保生成质量可交付：L1.文件完整性确认；L2.代码语法校验；L3.代码运行与错误修复（用户可选择）
- 自动生成校验报告

## v1.2.1

LLM的状态可为Agent软监控，避免LLM的超预期行为。

## v1.3

优化以下功能：

- 增量式开发（新增文件修改备份与diff记录，使关键修改可溯）

## v2

将原有的工具调用形式从Function Calling迁移为MCP协议，具体如下：

- 采用CS（MCP server/client）模式，将全部tool部署到server（8001端口）常驻
- 原agent主入口改造为MCP host+client，负责和LLM交互，然后通过HTTP对server进行端口访问来处理LLM的tool调用请求

下图展示了LLM发起工具调用请求后的单轮循环步骤。和v1一样，LLM收到用户的`TASK`后启动这个循环，直到所有文件写好且三级校验完毕。然后给MCP client发送final answer。

<img width="1477" height="527" alt="image" src="https://github.com/user-attachments/assets/f741cc4a-969a-4c2c-948e-701249936a2a" />

Bug修复：

- 取消了`PROJECT_DIR`变量的交叉引用，现在sever启动后，各client仍可使用自己的`PROJECT_DIR`
- 解决了原环境不支持多进程通信的问题

## v2.1

新增了功能：

- 可将工作模式切换为多agent协同：将编码-检错-测试闭环解离，分别调度给3个不同的agent，由统一的scheduler自动控制

## v2.2
新增了功能：
- 添加了RAG。现在用户发起提问，agent会先检索知识库里的内容然后一同发给LLM，如图5。由于v2.1引入了3个agent协同，所以每个agent都会在开始时进行1次RAG检索。RAG的详细策略为：
  - 分片&索引：根据不同的规范文件，分别构建不同的FAISS向量库
  - 检索策略：从不同向量库分别多路召回（强制每路都有召回内容）；使用BM25+Embedding联合排序算法

<img width="1030" height="364" alt="image" src="https://github.com/user-attachments/assets/bb16a83f-f5a7-4bc0-a0f2-4d102c670517" />

## v2.2.1
新增了功能：

- 联网搜索的缓存算法升级为：

  - TTL过期策略：每个条目定时强制删除
  - W-TinyLFU替换策略：更适合“幂律式：少量热点+大量低频检索”的场景
Tools修改：
- web_search重新实现，但参数不变
 
## v2.3
完善了多agent协同机制（代码修改全部在`mcp_cheduler.py`中完成）：
- 引入router，对用户的任务需求请LLM先进行分类。简单任务使用单agent策略，复杂任务才分发给多agent协同完成

增加了测试用例：
- 数据集1-MBPP：通用的Python代码题。位于`test_datas/mbpp`中。
- 数据集2-Keyan：基于EC领域的科研的真实代码需求搭建的任务集。位于`outputs/keyan`中。每个task是一个工作目录，里面有TODO.md，agent需要基于此需求文档在目录里增加/修改代码。
