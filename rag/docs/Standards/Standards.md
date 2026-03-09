# Company Coding Standards

> 本文档定义公司内部统一的编码规范（Standards），  
> 所有进入主分支（main/master）的代码 **必须遵循** 本规范。  
> 本规范适用于所有语言与技术栈，语言专项规范可在此基础上扩展。

---

## 1. 总体原则（General Principles）

所有代码必须遵循以下原则，按优先级排序：

1. **Correctness（正确性）**
2. **Readability（可读性）**
3. **Maintainability（可维护性）**
4. **Consistency（一致性）**
5. **Performance（性能）**

> ⚠️ 任何以“性能”为理由破坏可读性或正确性的代码，必须有明确 benchmark 和文档说明。

---

## 2. 代码结构规范（Project Structure）

### 2.1 目录结构

- 目录命名使用 **小写 + 下划线**
- 同一层级目录职责必须单一
- 禁止出现以下目录名：
  - `tmp/`
  - `test2/`
  - `old/`
  - `backup/`

**推荐结构示例：**
```

project/
├── src/
│   ├── core/
│   ├── utils/
│   └── services/
├── tests/
├── docs/
├── scripts/
└── README.md

````

---

## 3. 命名规范（Naming Conventions）

### 3.1 通用规则

- 命名必须**自解释**
- 禁止使用无意义名称
- 禁止使用拼音

**禁止：**
```python
a, b, tmp, data1, handle2
````

---

### 3.2 变量命名

| 类型   | 规范                           |
| ---- | ---------------------------- |
| 普通变量 | `lower_snake_case`           |
| 常量   | `UPPER_SNAKE_CASE`           |
| 布尔值  | 使用 `is_ / has_ / enable_` 前缀 |

**示例：**

```python
user_id
total_count
IS_PRODUCTION
is_valid
```

---

### 3.3 函数 / 方法命名

* 使用 **动词 + 名词**
* 明确行为与对象

**推荐：**

```python
load_config()
validate_user_input()
calculate_checksum()
```

**不推荐：**

```python
process()
do_work()
handle()
```

---

### 3.4 类命名

* 使用 `PascalCase`
* 名称必须是名词

```python
class UserService:
    pass
```

---

## 4. 函数与方法规范（Functions & Methods）

### 4.1 函数长度

* 单个函数 **≤ 50 行**
* 超过 50 行必须拆分
* 超过 80 行 **禁止合并**

---

### 4.2 单一职责

一个函数只能做一件事。

**判断标准：**

> 是否可以用一句话完整描述函数功能？

---

### 4.3 参数数量

* 参数 ≤ 5
* 超过 5 个参数：

  * 使用对象 / 配置结构
  * 或拆分函数

---

## 5. 注释规范（Comments）

### 5.1 什么时候必须写注释

* 业务规则复杂
* 非直观算法
* 临时 workaround
* 与历史问题相关的逻辑

---

### 5.2 注释规范

* 注释解释 **“为什么”**，而不是 **“做了什么”**
* 注释必须与代码保持一致
* 禁止注释掉大量无用代码

**推荐：**

```python
# 为兼容旧版本客户端，必须保留该字段（2024-03）
```

---

## 6. 错误处理规范（Error Handling）

### 6.1 基本规则

* 禁止吞掉异常
* 禁止使用裸 `except`
* 异常信息必须可定位问题

**禁止：**

```python
try:
    run()
except:
    pass
```

---

### 6.2 推荐做法

* 捕获具体异常
* 记录日志
* 必要时向上抛出

---

## 7. 日志规范（Logging）

### 7.1 日志级别

| 级别       | 使用场景  |
| -------- | ----- |
| DEBUG    | 调试信息  |
| INFO     | 正常流程  |
| WARNING  | 潜在问题  |
| ERROR    | 功能失败  |
| CRITICAL | 系统不可用 |

---

### 7.2 日志内容规范

* 必须包含上下文信息
* 禁止记录敏感信息
* 禁止在生产环境使用 `print`

---

## 8. 测试规范（Testing）

### 8.1 基本要求

* 核心逻辑必须有测试
* Bug 修复必须补测试
* 测试代码与业务代码同等重要

---

### 8.2 测试命名

* 测试函数必须清晰描述行为
* 推荐格式：

```text
test_<function>_<expected_behavior>
```

---

## 9. 代码格式（Formatting）

### 9.1 通用规则

* 使用 UTF-8 编码
* 每行最大长度 100 字符
* 文件末尾保留换行

---

### 9.2 自动格式化

* 所有项目必须使用统一格式化工具
* 禁止因格式问题产生 Review 噪音

---

## 10. Git 与提交规范（Git Standards）

### 10.1 提交粒度

* 一次提交只做一件事
* 禁止混合重构 + 功能 + 修复

---

### 10.2 Commit Message 规范

```text
type(scope): description
```

| type     | 含义  |
| -------- | --- |
| feat     | 新功能 |
| fix      | 修复  |
| refactor | 重构  |
| test     | 测试  |
| docs     | 文档  |
| chore    | 杂项  |

---

## 11. Code Review 强制要求

* 所有代码必须 Review
* 禁止自我合并
* 未通过 Review 不得进入主分支

---

## 12. 禁止行为（Hard Rules）

以下行为 **严格禁止**：

* 提交无法运行的代码
* 在主分支直接开发
* 使用魔法数字（magic number）
* 引入未使用的依赖
* 把 TODO 留在生产代码中

---

## 13. 规范的更新与例外

* 规范可随项目演进更新
* 所有例外必须：

  1. 有明确理由
  2. 有文档记录
  3. 经团队认可

---

## 14. 最终原则

> **代码是长期资产，不是一次性产物。**
> 请始终以“下一个维护你代码的人”为第一读者。

---

**Maintainers:** Engineering Committee
**Last Updated:** YYYY-MM-DD

```
