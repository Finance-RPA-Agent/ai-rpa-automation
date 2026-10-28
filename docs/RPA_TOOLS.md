# RPA 四工具使用说明（RPA_TOOLS.md）

本文档对应 `ai-rpa-automation-backend` 项目中“供应商财务数据核对与异常处理”场景的
四个可运行工具初版：

| 工具 | 作用 |
| --- | --- |
| `read_data_file` | 读取 `.xlsx` / UTF-8 `.csv`，返回带行号的记录 |
| `validate_data` | 字段/格式/业务键校验，可选与 BI 参考记录比对 |
| `query_bi` | 查询模拟 BI 供应商财务记录（按 supplier_id / order_id） |
| `submit_to_oa` | 将核对结果或异常事项归档到模拟 OA（幂等、关联任务） |

四工具是**可复用 Python 函数**；FastAPI 的 `/tools/*` 路由只是供前端或其他进程调用的
HTTP 入口，两者共用同一份实现（`backend/app/tools/`），没有复制两套规则。

> 定位说明：这只是四工具和演示编排的初稿。它没有接入真实 BI/OA，不是 AI Agent，
> 也不是完整产品。旧 Agent 工作流（关键词规则）**尚未**调用这四个工具，详见第 9 节。

---

## 1. 安装与启动

项目依赖没有新增，继续使用原 `requirements.txt`（fastapi、uvicorn、sqlalchemy、
pandas、openpyxl、python-multipart、pwdlib[argon2]、pytest、httpx）。

普通 Python 3.12 虚拟环境：

```bash
cd ai-rpa-automation-backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

本次验证使用的解释器是 `D:\ENT207开发\.venv-backend-review\Scripts\python.exe`
（Python 3.12.14，“借用预装包”的审阅环境）。项目本身没有在全新干净虚拟环境中重新
执行过 `pip install`，因此不能声称“干净安装已验证”。验证到的依赖版本：

```
fastapi 0.141.1 / pydantic 2.13.5 / SQLAlchemy 2.0.54
pandas 3.0.1 / openpyxl 3.1.5 / pytest 9.1.1 / httpx 0.28.1
```

启动后端：

```bash
uvicorn backend.app.main:app --reload
```

Swagger：`http://127.0.0.1:8000/docs`，新工具在 `RPA Tools` 分组下。

---

## 2. 配置与文件安全

`backend/app/config.py` 集中读取环境变量，默认值与项目原行为一致（相对项目根目录）：

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| `RPA_BASE_DIR` | 项目根目录 | 基础目录 |
| `RPA_DATABASE_URL` | `sqlite:///./ai_rpa.db` | SQLAlchemy 连接串（`database.py` 读取） |
| `RPA_UPLOAD_DIR` | `<base>/uploads` | 上传文件目录 |
| `RPA_DEMO_DATA_DIR` | `<base>/demo_data` | 演示/共享数据目录 |
| `RPA_OUTPUT_DIR` | `<base>/outputs` | 输出目录（保留给后续处理文件） |
| `RPA_MAX_UPLOAD_BYTES` | 10485760 | 上传大小上限 |

安全规则：

- 文件工具只允许读取 `RPA_UPLOAD_DIR` 和 `RPA_DEMO_DATA_DIR` 内的文件。
  绝对路径越界、`..` 穿越、解析后逃出根目录的符号链接都会被拒绝
  （错误码 `PATH_NOT_ALLOWED`）。
- `POST /tools/files` 不使用用户文件名落盘，而是 `uuid4().hex + 原扩展名`，
  同名上传不会覆盖已有文件；原件内容按字节保存，不做修改。
- 工具不提供 eval、动态导入或任意 SQL 能力；`/tools/execute` 只按固定白名单分发。

---

## 3. 统一返回契约

成功（业务异常也算成功，例如校验发现问题、BI 查询为空）：

```json
{"status": "success", "result": { ... }}
```

失败（技术性失败，不可继续）：

```json
{"status": "error", "error_code": "FILE_NOT_FOUND", "message": "可理解的错误说明"}
```

HTTP 层约定：

- HTTP 422 只表示 FastAPI 请求体本身不合法（例如缺少 `tool` 字段）；
- 未知工具、参数错误等返回 **HTTP 200 + 工具错误信封**，而不是 HTTP 4xx/5xx；
- `/tools/execute`、`/tools/files`、`/tools/oa/*` 都遵循上述信封。

错误码清单（`backend/app/tools/errors.py`）：

```text
FILE_NOT_FOUND / FILE_READ_ERROR / EMPTY_FILE / UNSUPPORTED_FILE_TYPE /
UNSUPPORTED_ENCODING / FILE_TOO_LARGE / SHEET_NOT_FOUND / PATH_NOT_ALLOWED /
INVALID_CSV_STRUCTURE / CSV_PARSE_ERROR /
INVALID_ARGUMENTS / UNKNOWN_TOOL / BI_QUERY_FAILED / TASK_NOT_FOUND /
INVALID_RECORD_TYPE / INVALID_DATA / RECORD_NOT_RECONCILED /
CONFLICTING_OPERATION / OA_SUBMISSION_FAILED / OA_RECORD_NOT_FOUND /
INTERNAL_ERROR
```

---

## 4. 字段与演示规则（集中维护）

规则集中在 `backend/app/tools/rules.py`，演示数据与预期结果集中在
`backend/app/services/demo_data.py`。

核心字段（7 个，演示中均为必需字段）：

```text
supplier_id, supplier_name, order_id, amount, date, payment_status, record_status
```

演示假设（**团队待确认，不是均胜已确认的制度**）：

- 业务组合键：`supplier_id + order_id`；同一文件内重复组合键报告
  `duplicate_business_key`，不同订单允许同供应商、同金额/日期/状态。
- 金额：单一货币、最多两位小数，内部用 `Decimal` 精确比较；`3.001` 直接
  报格式错误，不做静默四舍五入；负数按演示规则判为非法；布尔值、NaN、
  Infinity、空值均拒绝。
  - 文本金额先做整串格式校验，再处理千分位：合法形式只有
    “纯数字”或“1–3 位数字开头 + 每组恰好 3 位的逗号分组”，可选最多两位小数，
    例如 `5000`、`5000.50`、`1,250.50`、`1,000,000.01`。
  - 非法分组或模糊逗号（`50,00`、`5,,000`、`,5000`、`1,2345.00`、`1234,567`、
    `1,250.`、`.50`、`5 000`）一律报 `invalid_amount`，不会删逗号后猜测。
  - 校验与 `submit_to_oa` 的金额检查共用 `rules.parse_amount`，规则一致。
- 日期：`YYYY-MM-DD`；Excel 日期单元格（00:00:00）可接受；其余（含带时间、
  非 ISO、非法日历日）报 `invalid_date`。
- 表头：第一条记录为表头，第一条数据为第 2 行；`read_data_file` 返回行号。
  - 空/纯空白表头生成 `column_N` 并记 `empty_header`；重名表头（包括与已生成
    名字碰撞，如 `amount, amount, amount__2`）改为真正唯一的 `__N` 后缀并记
    `duplicate_header`，每个单元格按键位独立保留，不会被覆盖。
  - `validate_data` 会把表头的 `empty_header` / `duplicate_header` 作为文件级
    问题写入 `issues`，正常/冲突编排据此暂停，不会把表头歧义当成已核对。
- 行号语义：
  - XLSX 使用工作表真实行号；
  - CSV 使用物理行号：空白行会被跳过但仍计数，所以后续行号与文本编辑器一致；
    带引号的字段内换行会让该记录跨多行，记录行号指向其起始行。
- 标识符：文本原样保留，`00123`、`NA`、`N/A`、`NULL`、`None`、`nan` 都不会被
  当作缺失占位符；真实空单元格返回 `null`，校验报 `missing_value`。
- 校验采用行级计分：`invalid_rows` 按“有问题的行数”去重统计，一行多个问题只
  记一条无效记录；整列缺失、表头歧义属于文件级问题，不自动把每一行都算无效。
- 参考记录匹配到多条时报告 `ambiguous_reference`，绝不任取一条。
- 当 Excel 行有状态值时，匹配到的参考记录若缺少该状态或仅有空白，报
  `missing_reference_status`；类型不可用（如数组）报
  `invalid_reference_status`；值不同报 `*_mismatch`。缺失与“值不一致”是不同
  语义，都不会被当成已一致（Excel 本身缺失时已由 `missing_value` 报告）。

---

## 5. 工具详解

### 5.1 `read_data_file`

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `file_path` | 是 | 允许目录内的相对或绝对路径 |
| `sheet_name` | 否 | 仅 `.xlsx`；默认第一个工作表；`.csv` 传该参数会报 `INVALID_ARGUMENTS` |

成功 `result`：

```json
{
  "file_path": "…/demo_data/normal_orders.xlsx",
  "file_type": "xlsx",
  "sheet_name": "Sheet1",
  "header_row": 1,
  "first_data_row": 2,
  "row_count": 3,
  "columns": ["supplier_id", "..."],
  "column_issues": [],
  "records": [{"row": 2, "data": {"supplier_id": "SUP-001", "amount": 5000.0, "date": "2026-09-18", "...": "..."}}]
}
```

说明：

- `.xlsx` 与 UTF-8 / UTF-8 BOM `.csv` 支持；`.xls` 明确不支持（`UNSUPPORTED_FILE_TYPE`），
  不假装已支持未验证格式。
- 空文件 `EMPTY_FILE`；只有表头是成功且 `row_count=0`；损坏文件
  `FILE_READ_ERROR`；未知工作表 `SHEET_NOT_FOUND`。
- 表头处理：空/纯空白表头生成 `column_N`（`column_issues` 记 `empty_header`）；
  重名表头生成真正唯一的 `__N` 后缀并在 `column_issues` 记 `duplicate_header`。
  例如 `amount, amount, amount__2` 会得到三个唯一列名，三列数据全部保留，
  不会出现字典键覆盖。
- CSV 结构校验（严格模式）：
  - 数据行值个数 **多于** 表头列数时返回 `INVALID_CSV_STRUCTURE`，错误信息含
    行号和“实际值数 / 表头列数”，不截断、不丢弃多余值；行尾多一个逗号同样
    视为多一个空值并拒绝。
  - 数据行值个数 **少于** 表头列数时按缺失补 `null`，必要字段缺失由
    `validate_data` 的 `missing_value` 发现。
  - 使用 `csv.reader(strict=True)`：引号未闭合/语法错误返回 `CSV_PARSE_ERROR`，
    错误信息带行位置；工具不会猜补引号。
  - 合法行为保持不变：引号内逗号、双引号转义（`""`）、引号内换行、UTF-8 BOM。
- CSV 行号按物理行计算：空白行跳过但保留计数；带引号换行的字段会让记录跨行，
  记录行号指向起始行。XLSX 使用工作表真实行号。
- `records[].data` 保留原始值；文本编号 `00123`、`NA`、`N/A`、`NULL`、`None`、
  `nan` 都按文本保留，真实空单元格为 `null`。若前导零在源 Excel 数值单元格中
  已经丢失，工具不会猜测补回。
- `cells` 中 NaN、日期、Decimal 都会转换成合法 JSON（见第 7 节）。

Python 示例：

```python
from backend.app.tools import read_data_file

response = read_data_file(file_path="demo_data/normal_orders.xlsx")
print(response["result"]["records"][0]["data"]["supplier_id"])
```

HTTP 示例：

```json
POST /tools/execute
{"tool": "read_data_file", "arguments": {"file_path": "demo_data/normal_orders.xlsx"}}
```

### 5.2 `validate_data`

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `file_path` | 是 | 待校验文件 |
| `reference_records` | 否 | `None`=不做跨系统比对；`[]`=已查询但无匹配 |
| `sheet_name` | 否 | 仅 `.xlsx` |

`result` 主要字段：

```json
{
  "total_rows": 3, "valid_rows": 1, "invalid_rows": 2,
  "issues_count": 2,
  "issues": [
    {"row": 2, "field": "amount", "type": "amount_mismatch",
     "message": "Excel amount does not match the BI record; manual verification is required.",
     "excel_amount": 5200.0, "bi_amount": 5000.0, "difference": 200.0}
  ],
  "missing_columns": [],
  "duplicate_keys": [],
  "reference_compared": true,
  "reference_record_count": 6,
  "rule_set": {"required_fields": ["..."], "business_key": ["supplier_id", "order_id"], "amount_scale": 2, "date_format": "YYYY-MM-DD", "allow_negative_amount": false, "currency_mode": "single_currency_two_decimals"}
}
```

问题类型：

```text
文件级: missing_column / empty_dataset / invalid_reference_record /
        empty_header / duplicate_header
行级:   missing_value / invalid_amount / invalid_date /
        duplicate_business_key / record_not_found / ambiguous_reference /
        invalid_reference_amount / missing_reference_status /
        invalid_reference_status / amount_mismatch /
        payment_status_mismatch / record_status_mismatch
```

- 文件级问题（含表头歧义、整列缺失）会出现在 `issues` 中，但不会把每一行都
  计入 `invalid_rows`；
- `missing_reference_status`：匹配到的 BI 记录缺少必要状态，无法证明一致；
- `invalid_reference_status`：必要状态类型不可用（例如数组、对象）；
- 状态值不一致仍然报 `payment_status_mismatch` / `record_status_mismatch`。

约定：

- 校验成功即使发现问题也返回 `success`，问题在 `issues` 中；只有文件不可读等
  才是 `error`。
- 未匹配到 BI 记录报 `record_not_found`，不会当作金额 0。
- 默认不假设 BI 一定正确，只报告 Excel 值、BI 值和确定性差额
  （`difference = excel_amount - bi_amount`）。
- 校验不修改源文件、不自动改金额、不伪造缺失值。

### 5.3 `query_bi`

参数：`supplier_id` 与 `order_id` 至少一个，两个都传时按 AND 查询。

成功 `result`：

```json
{
  "records": [{"record_id": 1, "supplier_id": "SUP-001", "supplier_name": "ABC Ltd",
               "order_id": "ORD-1001", "amount": 5000.0, "date": "2026-09-18",
               "payment_status": "pending", "record_status": "active"}],
  "count": 1,
  "query": {"supplier_id": "SUP-001", "order_id": "ORD-1001"},
  "source": "simulated_bi_financial_records"
}
```

- 查不到时 `success` + `records: []`；真正的查询失败返回 `BI_QUERY_FAILED`，
  且 session 回滚后仍可继续使用。
- 数据来源是新增表 `bi_financial_records`（不是旧的 `bi_inventory` 库存表）。
- 初始化/更新演示数据（幂等，不会在服务启动时自动塞数据）：

```bash
python scripts/seed_demo_data.py
# 仅当确需清空演示表时（只清 bi_financial_records，不影响任务/用户等）：
python scripts/seed_demo_data.py --reset-demo-table
```

### 5.4 `submit_to_oa`

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `task_id` | 是 | 必须存在的任务 |
| `record_type` | 是 | `reconciliation_result` 或 `reconciliation_exception` |
| `data` | 是 | 结构化业务数据 |
| `operation_id` | 否 | 幂等操作标识；不传时按内容哈希自动生成 |

`reconciliation_result` 必需字段：`supplier_id, order_id, amount, date,
payment_status, record_status`，且 `record_status` 必须为 `matched`，否则返回
`RECORD_NOT_RECONCILED`（未解决冲突不能当正常结果提交）。

`reconciliation_exception` 必需字段：`supplier_id, order_id, issue_type`；
`issue_type=amount_mismatch` 时还需要可解析的 `excel_amount` 和 `bi_amount`。
异常记录落库后 `review_status` 固定为 `pending_review`（保持“待核实”语义）。

成功 `result`：

```json
{"record_id": "OA-20260918-0001", "record_type": "reconciliation_result",
 "submitted": true, "operation_id": "normal:1:SUP-001:ORD-1001",
 "review_status": "archived", "idempotent_replay": false, "ignored_fields": []}
```

幂等规则：

- 显式 `operation_id`：同任务同操作、同内容重试 → 返回原记录
  （`idempotent_replay=true`）；同操作、内容不同 → `CONFLICTING_OPERATION`。
- 不传 `operation_id`：使用 `auto:<内容哈希前16位>`。相同内容永远视为重试
  （不再新建），不同内容生成不同的自动标识、会新建记录。这是需要团队确认的
  兼容规则。
- 调用者传入 `confirmed`、`approved_by`、`approved`、`human_confirmed`、
  `authorized_by` 等“授权类”字段会被剥离并记录到 `ignored_fields`；工具不用
  调用者自报的 `confirmed=true` 冒充人工批准。
- 写入任务日志（action=`OA Reconciliation Record Submitted`，status=`submitted`，
  message 含 `operation_id`），所有校验通过后才写库，非法输入不会留下半条记录。

读取归档（用于演示和后续对账）：

```text
GET /tools/oa/records/{record_id}
GET /tools/oa/records?task_id=12
```

---

## 6. 统一调度入口 `/tools/execute`

请求体：

```json
{"tool": "query_bi", "arguments": {"supplier_id": "SUP-001", "order_id": "ORD-1001"}}
```

- 工具名必须是白名单之一，未知工具返回 `UNKNOWN_TOOL`；
- 参数只接受工具声明过的字段，多余字段（例如 `sql`）返回 `INVALID_ARGUMENTS`；
- 可用 `GET /tools` 查看工具清单与参数。

上传文件：

```bash
curl -F "file=@demo_data/normal_orders.xlsx" http://127.0.0.1:8000/tools/files
```

返回 `file_id`、`file_path`（可直接作为 `read_data_file.file_path`）等；
只接受 `.xlsx` / `.csv`，空文件和超限文件分别返回 `EMPTY_FILE` / `FILE_TOO_LARGE`。

Python 统一入口：

```python
from backend.app.database import SessionLocal
from backend.app.tools import execute_tool

with SessionLocal() as db:
    response = execute_tool(
        "query_bi",
        {"supplier_id": "SUP-001", "order_id": "ORD-1001"},
        db=db,
    )
print(response)
```

---

## 7. JSON 序列化与兼容变化

`backend/app/tools/serialization.py` 统一处理 Decimal、日期、NumPy 标量、NaN：
NaN/Infinity → `null`，日期/时间 → ISO 字符串，Decimal → 数字。

相对候选接口 V0.2 的**新增字段**（均为向后兼容，原字段名和语义保留）：

| 位置 | 新增 | 原因 |
| --- | --- | --- |
| `read_data_file.result` | `sheet_name`、`header_row`、`first_data_row`、`records[].row`、`column_issues` | 保留行号定位与表头问题 |
| `validate_data.result` | `issues_count`、`missing_columns`、`duplicate_keys`、`reference_compared`、`reference_record_count`、`rule_set` | 明确统计语义与演示规则 |
| `validate_data.issues[]` | `value`、`excel_amount`、`bi_amount`、`difference`、`excel_value`、`bi_value` | 展示冲突双方与确定性差额 |
| `query_bi.result` | `count`、`query`、`source`、`records[].record_id` | 便于前端和日志展示 |
| `submit_to_oa.result` | `operation_id`、`review_status`、`idempotent_replay`、`ignored_fields` | 幂等与“待核实”语义 |

字段名、核心字段集合与候选稿一致；没有另建第二套定义。

---

## 8. 任务状态与演示编排边界

工具函数只执行并返回结果，**不**推进任务全局状态。状态由
`backend/app/services/demo_workflow.py`（演示编排，未来由后端/Agent 集成层）管理：

| 情况 | 任务状态 |
| --- | --- |
| 正常链全部成功并归档 | `completed` |
| 正常链发现任何问题（表头歧义、缺值、格式、冲突） | `waiting_confirmation` |
| 冲突链发现可归档的金额/状态冲突并写入异常记录 | `waiting_confirmation` |
| 冲突链只有不可归档的格式/缺失/表头问题 | `waiting_confirmation`，不写 OA 记录，`unarchived_issues` 列出全部问题 |
| 冲突链同时有可归档冲突和不可归档问题 | `waiting_confirmation`，只归档冲突，`unarchived_issues` 保留其余问题 |
| 技术失败（文件读不到、工具报错） | `failed`（不会停在 `running`） |

冲突编排不再使用“只挑选了自己认识的冲突类型”这种判断：它先检查完整校验结果，
只要存在未解决问题就不会写 `completed`；状态、`task.result` 摘要和抛出的
`DemoFlowError` 内容保持一致。演示脚本在“预期外输入”时以非 0 退出并打印堆栈，
正常的两条演示输入仍然是退出 0。

演示命令（项目根目录）：

```bash
python scripts/seed_demo_data.py        # 幂等初始化模拟 BI 数据
python scripts/demo_normal_flow.py      # 正常链
python scripts/demo_conflict_flow.py    # 金额冲突链（结束为 waiting_confirmation）
python scripts/build_demo_files.py      # 由统一数据重新生成 demo_data/*.xlsx|csv
```

演示数据（`demo_data/`，合成数据，无企业真实数据）：

| 文件 | 预期 |
| --- | --- |
| `normal_orders.xlsx` | 3 行全部匹配，0 问题 |
| `missing_values.csv` | 2 个 `missing_value`，2 行无效 |
| `invalid_formats.xlsx` | `invalid_amount`、`invalid_date` 各 1 |
| `amount_conflict.csv` | `amount_mismatch`（5200 vs 5000，差 +200）与 `payment_status_mismatch` |
| `duplicate_keys.xlsx` | 2 个 `duplicate_business_key` |
| `no_match.csv` | `record_not_found`、`record_status_mismatch` |
| `leading_zero.csv` | 文本编号 `00123` 原样保留 |

演示脚本是**确定性编排**，不是已接入真实 AI Agent。

---

## 9. 如何接现有后端与未来 Agent

- 现有 FastAPI：`backend/app/main.py` 已注册 `tools.router`，所有新接口挂在同一应用下，
  没有另起一套服务；旧接口 URL 与响应未改。
- 新数据表：`bi_financial_records`（模拟 BI）与 `oa_reconciliation_records`（模拟 OA 归档），
  通过 `Base.metadata.create_all` 随服务启动创建，未修改旧表结构，未重置旧数据库。
- 未来 Agent 调用示例（伪代码）：

```python
from backend.app.database import SessionLocal
from backend.app.tools import execute_tool

def agent_step(tool_name, arguments):
    with SessionLocal() as db:
        return execute_tool(tool_name, arguments, db=db)

plan = agent_step("read_data_file", {"file_path": file_ref})
refs = agent_step("query_bi", {"supplier_id": sid, "order_id": oid})["result"]["records"]
check = agent_step("validate_data", {"file_path": file_ref, "reference_records": refs})
for issue in check["result"]["issues"]:
    if issue["type"] == "amount_mismatch":
        agent_step("submit_to_oa", {
            "task_id": task_id,
            "record_type": "reconciliation_exception",
            "data": {"supplier_id": sid, "order_id": oid,
                     "issue_type": "amount_mismatch",
                     "excel_amount": issue["excel_amount"],
                     "bi_amount": issue["bi_amount"]},
            "operation_id": f"exception:{task_id}:{sid}:{oid}:amount_mismatch",
        })
```

- **尚未切换的旧路径**（交接重点）：
  - `POST /excel/validate` 与 `POST /agent/run/{task_id}` 仍使用旧规则
    （逐列查重、负数检查），**没有**调用 `validate_data`；
  - `POST /office/rpa/fill/{task_id}` 仍生成旧的
    `finance_reimbursement_review` 摘要，**没有**调用 `submit_to_oa`；
  - `/bi/inventory` 仍是库存语义，与 `query_bi` 的财务记录是两套数据；
  - 旧 Agent 的 `parse_description` 仍是关键词规则，未接入语言模型。
  后续应由后端/Agent 方向决定切换计划；切换前不得声称“已整合”。

---

## 10. 验证方式

```bash
# 项目根目录
pytest tests/test_api.py                # 原有 5 项基础测试
pytest                                  # 全量：170 passed（含 F1-F7 回归 46 项、CSV 结构回归 13 项）
python scripts/demo_normal_flow.py
python scripts/demo_conflict_flow.py
```

- 测试使用独立的临时数据库与临时目录，不触碰 `ai_rpa.db`；演示脚本默认使用项目
  数据库，也可用 `RPA_DATABASE_URL` 指向隔离的 SQLite 文件（推荐演示时这样做）。
- Windows 下共享临时目录可能有权限限制时，加
  `-p no:cacheprovider --basetemp <工作区内全新目录>`。
- `tests/test_acceptance_fixes.py` 是第一轮独立验收 F1—F7 的项目回归测试；
  `tests/test_csv_structure.py` 是第二轮 CSV 结构校验（R2-1/R2-2）的项目回归测试。
- 实际测试与演示结果见 `docs/RPA_HANDOFF.md`。
