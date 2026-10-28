# Week 2 本机测试结果

日期：2026-09-17，Asia/Shanghai。**本机已验证**：requirements 安装成功，原有测试 `5 passed, 6 warnings`，新增契约后的完整测试 `48 passed, 6 warnings`，两次 pytest 退出码均为 0。失败测试：无。

此结果仅适用于本次 Python/依赖组合、现有五个 API 冒烟测试和 43 个独立 schema 校验用例；供应商业务流程、模型输出、真实工具写入与权限控制仍未验证。

## 1. 仓库与环境

- 仓库：`C:\Users\Administrator\Desktop\课件\大三上\ENT207\repos\ai-rpa-automation`。
- 分支：`week2-agent-validation`，从 `origin/backend` 创建，无上游。
- HEAD：`6be9dc0d20a18d44d7f4f4343e4260dd00eb7b99`。
- Python：**3.12.10**，64 位 Windows；实际版本原文：

```text
3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
```

- 基础解释器：`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`。
- 独立虚拟环境解释器：`C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-agent-venv\Scripts\python.exe`。
- 此前发现的 bundled Python 3.12.14 未用于此次项目测试。符合团队 Python 3.12.x 约定，未修改系统 Python 或已有环境。
- 原有测试在新增 schema 后单独指定 `tests/test_api.py` 执行；它和全部现有后端文件未改动。

## 2. 依赖安装

**实际结果：成功，退出码 0。** 依赖来自仓库原有 requirements.txt，未改依赖文件。

首次沙箱内安装长期无进展，环境当时仍只有 pip；主动中断（退出码 1），未视为安装成功，也没有将其记成 pytest 失败。随后沙箱外限时重试成功；未充分定位初次停滞的根因，不据此断言是仓库兼容问题。

PowerShell 实际成功安装命令（ENT207 工作目录）：

```powershell
& '.\.local\week2-agent-venv\Scripts\python.exe' -m pip install -r 'repos\ai-rpa-automation\requirements.txt' --disable-pip-version-check --no-input --keyring-provider disabled --timeout 15 --retries 1 --log '.local\week2-dependency-install.log'
```

`python -m pip check` 实际输出 `No broken requirements found.`，退出码 0。未额外安装 Ollama、Qwen、模型权重或 LLM SDK。

requirements 未锁版本；下表组合在本机通过，不代表团队已冻结这些版本。Pydantic v2 经 FastAPI 安装，本预研使用其 v2 API，其他版本组合未验证。

实际 `pip freeze --all` 快照：

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
argon2-cffi==25.1.0
argon2-cffi-bindings==26.1.0
certifi==2026.7.22
cffi==2.1.1
click==8.5.0
colorama==0.4.6
et_xmlfile==2.0.0
fastapi==0.141.1
greenlet==3.5.6
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.19
iniconfig==2.3.0
numpy==2.5.3
openpyxl==3.1.5
packaging==26.3
pandas==3.0.5
pip==25.0.1
pluggy==1.6.0
pwdlib==0.3.1
pycparser==3.0
pydantic==2.13.5
pydantic_core==2.46.5
Pygments==2.21.0
pytest==9.1.1
python-dateutil==2.9.0.post0
python-multipart==0.0.32
six==1.17.0
SQLAlchemy==2.0.54
starlette==1.6.0
typing-inspection==0.4.4
typing_extensions==4.16.0
tzdata==2026.4
uvicorn==0.53.0
```

## 3. 原有测试实际运行

工作目录：`C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-test-original`。

调用独立 venv 解释器，设置 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONIOENCODING=utf-8`，执行：

```text
python -m pytest -c C:\Users\Administrator\Desktop\课件\大三上\ENT207\repos\ai-rpa-automation\pytest.ini C:\Users\Administrator\Desktop\课件\大三上\ENT207\repos\ai-rpa-automation\tests\test_api.py -p no:cacheprovider
```

原始摘要原文：

```text
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
collected 5 items
======================== 5 passed, 6 warnings in 1.14s ========================
pytest_exit_code=0
```

实际通过：test_root、test_system_status、test_users_list、test_invalid_task、test_invalid_user。失败测试及原因：**无失败**。未修改现有测试或通过跳过用例获取结果。

## 4. 新增契约后完整测试实际运行

工作目录：`C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-test-final`。

同一解释器/环境和 pytest 配置，执行整个 tests 目录：

```text
python -m pytest -c C:\Users\Administrator\Desktop\课件\大三上\ENT207\repos\ai-rpa-automation\pytest.ini C:\Users\Administrator\Desktop\课件\大三上\ENT207\repos\ai-rpa-automation\tests -p no:cacheprovider
```

原始摘要原文：

```text
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
collected 48 items
======================= 48 passed, 6 warnings in 0.71s ========================
pytest_exit_code=0
```

组成：现有 API 5 个 + 新增 schema 参数化测试 43 个。失败测试及原因：**无失败**。

**本机已验证**的契约范围：

- 正常结构化输出与 JSON 往返校验；六状态输入/输出。
- 严格类型、有效 task_id、非空请求、多余字段和非法状态拒绝。
- 候选工具白名单、去重；next_tool 必须属于输入的 allowed_tools；输出自行增加白名单不能生效；缺校验上下文或空白名单时拒绝调用请求。
- completed/failed/cancelled 输入不能产生下一工具选择。
- waiting_confirmation、确认标记、确认 scope 和工具选择之间的一致性；scope 与 task 绑定。
- 不接受付款、转账、最终审批、删除记录的确认动作枚举。
- 递归拒绝明确 Python/Shell/SQL/浏览器脚本载荷键。
- missing_required_field/format_issue/amount_conflict/record_conflict/record_not_found 属业务异常，tool_error 属工具失败；混用类别拒绝。

这些是消息校验结果，**不是**上述业务异常实际被工具检测成功、不是确认已被授权、不是任务已经恢复执行。schema 未导入现有路由，测试未调用模型、企业系统或财务操作。

## 5. 六条警告

两次运行出现同样的六条弃用警告，均非测试失败：

| 来源 | 警告 | 本次处理 |
|---|---|---|
| FastAPI/Starlette TestClient | httpx 支持弃用，提示未来使用 httpx2 | 记录；本周不擅自改 requirements |
| Starlette/AnyIO | anyio.abc.BlockingPortal 别名弃用 | 记录；不修改依赖源码 |
| TaskResponse、TaskLogResponse、UserResponse、ApprovalResponse | Pydantic class Config 弃用，共四条 | 记录；不重构现有后端 |

## 6. 运行文件隔离与原始记录

database.py 使用相对 SQLite 路径且 main 导入时建表，因此从上述两个仓库外目录运行，以保持原有代码不变并隔离产物。两处各生成 `ai_rpa.db`（57,344 字节）；本次没有生成 uploads/outputs 文件。数据库保留在本机运行目录，不放入仓库、不提交。

以下原始记录也在仓库外，便于本机复查；报告已保存必要摘要和全部版本，其他机器不能依靠本机路径访问：

- `C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-dependency-install.log`
- `C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-installed-versions.txt`
- `C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-pytest-original.log`
- `C:\Users\Administrator\Desktop\课件\大三上\ENT207\.local\week2-pytest-final.log`

原始 pytest 输出通过 Tee-Object 完整保存；末尾退出码已从执行工具实际返回核对。缓存插件关闭，字节码生成关闭。没有凭据、API Key、密码、模型、数据库或上传/输出产物被加入 Git。

## 7. 完成范围及剩余问题

- **本机已验证**：克隆、fetch、五个远程分支可见、本地分支、依赖安装、pip check 和上述测试。
- **代码已实现**：原有规则式 API/工具原型以及独立 Agent 数据契约；现有后端/测试/依赖文件未修改。
- **仅设计**：供应商主线、候选工具与业务字段最终规范、正式人工确认和恢复策略。
- **未验证**：供应商端到端流程、共享真实预期样例、业务工具失败处理、确认恢复事件持久化、权限安全、Ollama/Qwen 和真实 BI/OA。

本周任务完成无阻塞。共享字段、唯一工具定义与样例仍需后端/AI/RPA 共同确认，阻塞未来业务实现，但不阻塞本次独立 schema 预研。建议先完成共同确认，Week 4+ 再按授权修改运行链路。未 commit、push、创建 PR 或合并任何分支。
