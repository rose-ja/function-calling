# Function Calling 工具治理

用 Python 标准库实现的一套 Agent 工具调用治理层。核心主张只有一句：

> **模型只负责提出调用意图，能否执行、执行几次、是否已经生效，全部由应用决定。**

这个项目不是「怎么把工具挂给模型」的示例，而是「挂上去之后怎么保证它不出事」的完整实现：统一结果协议、Schema 驱动的参数校验、读写风险分级、确认门槛、幂等键、超时与重试策略、以及一个带预算和停止原因的 Agent 循环。

- 纯标准库，无任何第三方依赖
- Python 3.10+（实际开发与验证环境：Python 3.14.2）
- 157 个测试用例，10 个测试文件，按层隔离
- 全部工具使用本地模拟数据，可离线运行，不访问网络

## 一、它解决什么问题

让模型调用工具很容易，难的是下面这些情况：

| 问题 | 不处理会怎样 |
|---|---|
| 模型幻觉出不存在的工具名 | 无法执行，模型也不知道有哪些工具可用 |
| 模型传入错误类型的参数 | 工具内部抛异常，堆栈泄露到模型 |
| 写操作被重复提交 | 同一条数据被创建两次 |
| 写入请求超时 | 不知道有没有生效，重发就制造重复数据 |
| 上游服务抖动 | 高频重试把已经撑不住的上游继续加压 |
| 模型试图读别人的数据 | 传入 `owner_id` 就能越权 |
| 模型陷入循环 | 无限调用工具，烧额度、拖死请求 |
| 需要用户确认的动作 | 模型自己「确认」了自己的操作 |

这套实现把上述每一个都变成了一个明确的结构约束或错误码。

## 二、架构分层

依赖方向严格单向，无循环导入。

```
用户请求
  │
  ▼
agent_loop.py       模型循环：轮数/调用数/纠错预算、五类停止原因、结果回传
  │  ← 不可信的 tool_name + arguments
  ▼
dispatcher.py       工具名白名单、确认策略、异常兜底
  │
  ▼
guard.py            幂等检查、参数校验、超时、重试
  │
  ▼
tool_spec.py        run_tool：结构校验前置，然后执行 handler
tool_schema.py      按 JSON Schema 子集校验参数
  │
  ▼
*_tool.py           只写业务规则，只返回 tool_core.ToolResult
```

横向支撑两个模块：

```
tool_core.py        结果协议（ToolResult / ToolError / ErrorType / ExecutionState）
request_context.py  请求身份（RequestContext + ContextVar + 跨线程传播）
```

静态依赖链：

```
main.py ─→ dispatcher.py ─→ guard.py ─→ tool_spec.py ─→ tool_schema.py
                        ↘  *_tool.py  ↗                 tool_core.py（叶子节点）
```

两个刻意的约束：

- `tool_core.py` 只依赖标准库，因此任何层都能安全引用它。
- `tool_spec.py` **不导入任何具体工具**。这是工具模块必须自行构造 `ToolSpec` 的原因——否则会立刻形成循环导入。

判断分层是否成立的唯一标准：**加一个新工具时，基础设施需不需要改。** 本工程从第 2 个工具做到第 5 个工具的过程中：

| 文件 | 改动 |
|---|---|
| `tool_schema.py` | 0 行 |
| `tool_spec.py` | 0 行 |
| `dispatch_tool` 函数体 | 0 行 |
| `tool_core.py` | 只增加错误码枚举项（错误码目录本就该随治理能力增长） |
| `guard.py` | 第 6 步改动一处：为支持身份传播，在提交任务前 `copy_context()` |
| `dispatcher.py` | 只增删注册表条目 |

## 三、目录结构

### 基础设施

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/tool_core.py` | 92 | 结果协议：`ToolResult` / `ToolError` / `ErrorType` / `ExecutionState` |
| `app/tool_schema.py` | 179 | JSON Schema 子集校验器，返回带字段路径的问题列表 |
| `app/tool_spec.py` | 67 | `ToolSpec` 工具契约 + `run_tool`（校验前置） |
| `app/guard.py` | 218 | 治理层：`RetryPolicy` / `IdempotencyStore` / `run_with_guard` |
| `app/dispatcher.py` | 68 | 注册表 + `dispatch_tool`（白名单、确认策略、异常兜底） |
| `app/request_context.py` | 75 | 请求身份与 `ContextVar` 跨线程传播 |
| `app/agent_loop.py` | 264 | Agent 循环、预算、停止原因、结果回传、幂等键推导 |

### 工具

| 文件 | 行数 | 工具名 | 类型 |
|---|---|---|---|
| `app/weather_tool.py` | 63 | `get_weather` | read |
| `app/exchange_rate_tool.py` | 88 | `get_exchange_rate` | read |
| `app/search_tool.py` | 127 | `search` | read |
| `app/todo_tool.py` | 175 | `list_todos` / `create_todo` | read / write |

### 入口与辅助

| 文件 | 行数 | 用途 |
|---|---|---|
| `app/main.py` | 296 | 演示入口：契约输出、只读输入矩阵、三层治理演示、Agent 循环演示 |
| `run_tests.py` | 47 | 统一测试入口，自动处理模块搜索路径 |
| `trace_guard.py` | 241 | 治理层专项演示：7 个场景逐一展示超时、重试、幂等的真实轨迹 |

### 测试（按层隔离）

| 文件 | 行数 | 覆盖层 |
|---|---|---|
| `test/test_tool_core.py` | 68 | 结果协议 |
| `test/test_tool_schema.py` | 70 | 校验引擎 |
| `test/test_tool_spec.py` | 88 | 工具契约与构造期约束 |
| `test/test_dispatcher.py` | 150 | 分发策略 |
| `test/test_weather_tool.py` | 47 | 业务规则（只读） |
| `test/test_exchange_rate_tool.py` | 127 | 业务规则（只读，含金额精度） |
| `test/test_search_tool.py` | 123 | 业务规则（只读，含空结果语义） |
| `test/test_todo_tool.py` | 303 | 业务规则（写入，含身份与业务去重） |
| `test/test_guard.py` | 379 | 超时、重试、幂等 |
| `test/test_agent_loop.py` | 430 | 循环停止条件与纠错预算 |

## 四、快速开始

```bash
# 运行全部测试（无需手动设置 PYTHONPATH）
python run_tests.py

# 查看完整演示
python app/main.py

# 单独观察治理层行为
python trace_guard.py
```

预期测试结果：

```
Ran 157 tests in ...s

OK
```

`app/main.py` 的输出分为四段：注册表治理清单、发给模型的工具契约 JSON、只读工具的输入矩阵、三层治理演示（幂等 / 待办工具 / Agent 循环）。

> **导入约定**：`app/` 下的模块之间以及测试文件都使用**顶层导入**（`from tool_core import ...`）。`run_tests.py` 会把 `app/` 加入模块搜索路径。如果某个文件写成 `from app.tool_core import ...`，它会立刻报 `ModuleNotFoundError`——这是刻意的，避免同一个模块被加载成两份不同的对象。

## 五、工具清单

| 工具名 | 类型 | 确认 | 超时 | 超时可重试 | 幂等键 |
|---|---|---|---|---|---|
| `get_weather` | read | 否 | 3s | 是 | 否 |
| `get_exchange_rate` | read | 否 | 3s | 是 | 否 |
| `search` | read | 否 | 3s | 是 | 否 |
| `list_todos` | read | 否 | 3s | 是 | 否 |
| `create_todo` | write | **是** | 5s | **否** | **是** |

待办的读和写拆成两个工具名，而不是一个工具带 `action` 参数——因为 `requires_confirmation` 是按工具名配置的。合成一个名字，要么读操作被无谓拦一次确认，要么写操作失去确认。

### 为什么有些字段「不该存在」

`create_todo` 的 Schema 里**没有** `owner_id`。待办归属只能来自请求身份；只要这个字段存在，模型就能传别人的 id 去读写别人的数据。多传一个会被 `additionalProperties: false` 挡掉：

```
模型伪造 owner_id：INVALID_ARGUMENTS（$.owner_id 不允许的字段）
```

## 六、错误码目录

| 分类 | 错误码 | 默认处理 |
|---|---|---|
| 分发 | `INVALID_TOOL_NAME` | 不执行 |
| 分发 | `UNKNOWN_TOOL` | 回报可用工具清单，模型可纠正 |
| 校验 | `INVALID_ARGUMENTS` | 不执行，回报字段路径（如 `$.city`） |
| 身份 | `IDENTITY_REQUIRED` | 不执行，属于调用方错误 |
| 权限 | `PERMISSION_DENIED` | 拒绝，重试无意义 |
| 确认 | `CONFIRMATION_REQUIRED` | 交回用户，**不是失败** |
| 幂等 | `MISSING_IDEMPOTENCY_KEY` | 拒绝执行 |
| 幂等 | `DUPLICATE_REQUEST` | 返回 `unknown` 状态 |
| 治理 | `TIMEOUT` | 只读可重试，写入不可 |
| 治理 | `UPSTREAM_UNAVAILABLE` | 只读可有限重试 |
| 治理 | `INTERNAL_ERROR` | 只记日志，不重试 |
| 业务 | `CITY_NOT_SUPPORTED` | 模型应换参数 |
| 业务 | `RATE_NOT_SUPPORTED` | 模型应换参数 |
| 业务 | `TODO_ALREADY_EXISTS` | 业务去重，未写入 |
| 业务 | `INVALID_TIME_RANGE` | 未写入 |
| 业务 | `CALENDAR_CONFLICT` | 预留，尚未使用 |

错误码决定了**模型的下一步动作**：`INVALID_ARGUMENTS` 让模型改格式，`CITY_NOT_SUPPORTED` 让模型换城市，`CONFIRMATION_REQUIRED` 让交互停下来等人。把这三类混成一个 `FAILED`，模型的纠错能力就全部失效。

## 七、执行状态

写入类工具失败后，必须先回答「到底有没有生效」。

| 状态 | 含义 | 出现场景 |
|---|---|---|
| `not_executed` | 确定没有产生业务效果 | 参数错误、业务拒绝、权限不足 |
| `executed` | 已经生效 | 部分成功（预留，尚未使用） |
| `unknown` | **不知道有没有生效** | 写入超时、并发重复请求被拒 |

`unknown` 的来源在 guard 的超时处理里：`future.result(timeout=...)` 超时时，那个函数还在另一个线程里跑，它跑完之后的返回值**没有任何地方接收**。所以应用无法判断业务数据到底改没改。

## 八、关键设计

### 8.1 治理规则放在构造期，而不是调用路径里

`ToolSpec.__post_init__` 里的两条约束：

```python
        if self.requires_confirmation and self.risk_level != "write":
            raise ValueError("只有写入工具才需要用户确认")
        if self.retryable_on_timeout and self.risk_level != "read":
            raise ValueError("写入工具超时后不允许直接重试，必须先确认执行状态")
```

这意味着只要有人试图把写入工具配成「超时后自动重试」，`ToolSpec` 对象根本创建不出来。治理规则不可能被忘记，因为它不是一个 if，而是一个构造约束。

### 8.2 一份 Schema，两个用途

`ToolSpec.parameters` 既发给模型，也用于运行时校验，消除「Schema 和代码各写一套、逐渐不一致」的隐患。测试里有一条锁定这个设计：`to_model_schema()` 输出的 `parameters` 必须**就是**那份 Schema 本身，不是复制品。

### 8.3 分发器的检查顺序不可调换

```python
    # 1. 工具名是合法字符串  → INVALID_TOOL_NAME
    # 2. 工具在注册表中      → UNKNOWN_TOOL
    # 3. 需要确认的是否已确认 → CONFIRMATION_REQUIRED
    # 4. 幂等键检查 → 参数校验 → 超时与重试
```

第 3 步必须在第 4 步**之前**：先判权限，再判执行前置条件。顺序反了就等于把权限判断交给了参数合法性。第 2 步也必须在参数校验之前，否则模型可以用构造参数的方式去试探未注册的工具。

注册表用固定字典，绝不用 `globals()[tool_name]` 或 `eval`——模型输出不是可信代码。

### 8.4 超时的三个硬事实

**`future.result(timeout=...)` 只结束等待，不结束执行。** 超时后 `future.cancel()` 只能作用于尚未开始的任务。

**线程池必须全局复用。** 每次调用新建线程池，`with` 退出时默认 `shutdown(wait=True)` 会等待那个卡住的线程跑完，超时机制直接失效。

**超时后必须区分读写。** 只读按 `not_executed` 处理（无副作用，允许重试）；写入标记 `unknown`。

### 8.5 幂等的核心是 `claim`，不是 `lookup`

```python
    def claim(self, key: str) -> bool:
        """抢占执行权。检查与占位在同一把锁内完成，避免并发请求重复执行。"""
        with self._lock:
            if key in self._results or key in self._in_flight:
                return False
            self._in_flight.add(key)
            return True
```

如果写成「先 `lookup` 看没有，再执行，再 `store`」，两个并发请求会同时发现键不存在，然后各执行一次——第二次的真实数据已经产生，台账救不回来。

`lookup` 是问「做完了吗」，`claim` 是问「我能开始吗」。要防并发必须用后者。

另外两条规则：**参数不合法时释放键**（那不是有效的业务请求，不该占用键），**失败结果也要记录**（否则重放会再次执行）。

### 8.6 身份只能来自会话，且必须跨线程传播

`ContextVar` 是线程局部的，而 `ThreadPoolExecutor` **不会**自动继承调用方的上下文（实测：直接提交得到默认值，`copy_context()` 后提交才拿到主线程设置的值）。所以 guard 在提交任务前显式捕获：

```python
    captured = capture_for_thread()          # = copy_context()
    future = _EXECUTOR.submit(captured.run, run_tool, spec, arguments)
```

身份用 `token` + `finally` 还原，而不是 `set(None)`——嵌套时内层退出必须恢复外层的值。

### 8.7 Agent 循环：五类停止原因

| 停止原因 | 性质 |
|---|---|
| `ROUND_LIMIT` / `CALL_LIMIT` / `CORRECTION_LIMIT` | 预算型保护 |
| `CONFIRMATION_REQUIRED` | **权限型中断，不是失败** |
| `MODEL_OUTPUT_EXHAUSTED` | 模型服务异常 |

把 `CONFIRMATION_REQUIRED` 混成一个 `failed` 状态会让用户以为系统坏了，其实它在等自己点确认。这条分支是 `return` 而不是 `continue`——否则模型会换个工具或参数试图绕过确认。

循环用 `for` 而不是 `while True`：只要循环体没有提前 `return`，就一定落到循环外的 `ROUND_LIMIT`，上限由结构保证。

### 8.8 纠错预算 ≠ 重试预算

| | 参数纠错 | 执行重试 |
|---|---|---|
| 触发 | `UNKNOWN_TOOL` / `INVALID_ARGUMENTS` | `TIMEOUT` / `UPSTREAM_UNAVAILABLE` |
| 谁发起 | 模型重新提出调用 | guard 自动重试 |
| 工具执行了吗 | **没有** | **执行了**（可能已有副作用） |
| 计数 | `AgentBudget.max_corrections` | `RetryPolicy.max_attempts` |

只有「请求本身写错了」才计入纠错预算。业务错误、权限错误、超时都是事实，模型重提一次不会改变结果——把它们算作纠错，正常对话会在第二轮就被打断。

### 8.9 回传给模型的内容是安全边界

`serialize_result` 是唯一一处定义回传格式的地方，只输出四要素：错误码、可读说明、是否可重试、执行状态。内部堆栈与内部标识永远不出现在这里。测试断言结果里不含 `traceback` / `postgres` / `stack`。

工具名错误时额外附带 `available_tools`（只含注册表里的名字）。参数错误则不带——模型缺的是参数知识，不是工具清单。

### 8.10 循环里的幂等键用参数指纹

```python
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
```

三个细节：

- `sort_keys=True`：换字段顺序不能算成两次请求。
- 用 `hashlib.sha256` 而不是内置 `hash()`：字符串的 `hash()` 在 Python 3.3+ 带随机盐，**进程重启后同一个参数会得到不同的值**，幂等键彻底失效。
- 明确记下取舍：如果业务允许「同样内容创建两次」，就不能用参数指纹，必须让调用方显式提供业务意图标识。

## 九、测试策略

**测哪一层就 import 哪一层。** 这是分层是否清晰的试金石。

几个高价值断言：

**证明校验先于执行**——用空的接收列表证明 handler 一次都没被调用：

```python
    def test_invalid_arguments_never_reach_handler(self) -> None:
        received: list[object] = []
        result = run_tool(spec, {"unexpected": 1})
        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertEqual(received, [])
```

**证明确认中断不落库、且不空转**：

```python
        self.assertEqual(run.stop_reason, "CONFIRMATION_REQUIRED")
        self.assertEqual(list_titles(context()), [])          # 一条数据都没落库
        self.assertEqual(len(model.seen_histories), 1)        # 只调用了一次模型
```

**证明幂等只执行一次**：用计数器统计 handler 的真实执行次数。幂等效果从返回值上看不出来（两次都返回成功），只有统计执行次数才能证明第二次没有真的执行。

**证明业务错误不消耗纠错预算**：`max_corrections=1` 但业务错误连查 3 次，循环依然正常完成。
