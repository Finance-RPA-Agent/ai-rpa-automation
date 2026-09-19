# 四工具初版交接说明（RPA_HANDOFF.md）

本文件记录本次“四工具可运行初版”的实际改动、验证结果、假设与遗留事项。
最终验收由另一位审阅者独立进行；本文中的测试与演示结果均为本机实际运行结果，
不代表独立审阅已通过。

- 工作目录：`D:\ENT207开发\ai-rpa-automation-backend`
- 验证解释器：`D:\ENT207开发\.venv-backend-review\Scripts\python.exe`（Python 3.12.14）
- 未提交、未推送、未创建 PR、未操作远程仓库；项目为 ZIP 解压副本。
- 原有接口、原有测试、其他成员文件未被删除或改名。

---

## 1. 改动文件清单

### 新增：工具核心（可复用 Python 逻辑）

| 文件 | 用途 |
| --- | --- |
| `backend/app/config.py` | 环境变量配置（数据库、上传/演示/输出目录、上传上限） |
| `backend/app/tools/__init__.py` | 四个工具与调度入口的统一导出 |
| `backend/app/tools/errors.py` | `ToolError`、稳定错误码、成功/失败信封 |
| `backend/app/tools/rules.py` | 核心字段、业务键、金额/日期/状态演示规则（集中维护） |
| `backend/app/tools/serialization.py` | Decimal/日期/NaN/NumPy → 合法 JSON |
| `backend/app/tools/file_reader.py` | `read_data_file`：安全路径解析、xlsx/csv 读取、行号、表头问题 |
| `backend/app/tools/validation.py` | `validate_data`：行内校验、业务键查重、BI 比对、统计 |
| `backend/app/tools/bi_query.py` | `query_bi`：按供应商/订单查询模拟 BI 财务记录 |
| `backend/app/tools/oa_submitter.py` | `submit_to_oa` 及归档读取：持久化、幂等、待核实语义、日志 |
| `backend/app/tools/dispatcher.py` | 固定工具白名单与 `execute_tool` 统一分发 |

### 新增：FastAPI 接入

| 文件 | 用途 |
| --- | --- |
| `backend/app/routers/tools.py` | `GET /tools`、`POST /tools/execute`、`POST /tools/files`、`GET /tools/oa/records*` |
| `backend/app/services/demo_data.py` | 合成 BI 数据与 7 个演示样例的**统一**预期结果 |
| `backend/app/services/finance_seed.py` | 幂等 seed 逻辑 |
| `backend/app/services/demo_workflow.py` | 正常链/冲突链确定性编排与任务状态管理 |
| `backend/app/services/__init__.py` | 服务层导出 |

### 新增：脚本、演示数据与文档

| 文件 | 用途 |
| --- | --- |
| `scripts/seed_demo_data.py` | 幂等初始化模拟 BI 数据；`--reset-demo-table` 只清演示表 |
| `scripts/build_demo_files.py` | 由统一数据生成 `demo_data/` 输入文件 |
| `scripts/demo_normal_flow.py` | 正常链演示（读取→查询→校验→保存→读回） |
| `scripts/demo_conflict_flow.py` | 金额冲突链演示（输出双方与差额、归档待核实） |
| `demo_data/*.xlsx / *.csv`（7 个） | 合成演示文件，无企业真实数据 |
| `docs/RPA_TOOLS.md` | 安装、启动、演示、工具参数/返回/错误码、接入示例 |
| `docs/RPA_HANDOFF.md` | 本文件 |

### 修改（最小改动，保持兼容）

| 文件 | 改动 |
| --- | --- |
| `backend/app/database.py` | 仅增加 `RPA_DATABASE_URL` 环境变量，默认值与原行为一致 |
| `backend/app/models.py` | 新增 `FinancialRecord`、`OaReconciliationRecord` 两张表；旧表未改 |
| `backend/app/main.py` | 注册 `tools.router`；原有路由不动 |

### 新增：测试

| 文件 | 测试数 | 覆盖 |
| --- | --- | --- |
| `tests/conftest.py` | - | 临时数据库/目录隔离；xlsx/csv 文件工厂 |
| `tests/test_read_data_file.py` | 21 | xlsx/csv/BOM/前导零/工作表/空文件/坏表头/路径越界/JSON 安全 |
| `tests/test_validate_data.py` | 23 | 缺列/缺值/金额/日期/重复键/BI 比对/统计语义/源文件不变 |
| `tests/test_query_bi.py` | 6 | 组合条件/空结果/参数校验/查询失败后 session 可用 |
| `tests/test_submit_to_oa.py` | 16 | 两类记录/读回/幂等/冲突/非法输入/日志/提交失败重试 |
| `tests/test_tools_dispatcher.py` | 9 | 白名单/未知工具/参数过滤/四工具经调度 |
| `tests/test_tools_api.py` | 11 | HTTP 上传、同名不覆盖、422 与信封、四工具经 API |
| `tests/test_demo_data.py` | 15 | 提交的演示文件与统一预期逐项对照（防漂移） |
| `tests/test_demo_workflows.py` | 5 | 正常/冲突/技术失败状态、无残留 running、源文件不变 |

### 未改动（有意保留）

`routers/excel.py`、`bi.py`、`office.py`、`agent.py`、`tasks.py`、`reports.py`、
`system.py`、`users.py`、`tests/test_api.py`、`README.md`、`requirements.txt`
（本次未新增依赖）。

---

## 2. 逐项完成状态

| 要求 | 状态 | 说明 |
| --- | --- | --- |
| 四个工具可复用 Python 实现 | 完成 | `backend/app/tools/`，同名函数可直接导入调用 |
| 统一调度入口 | 完成 | `execute_tool` + `POST /tools/execute`，固定白名单 |
| 接入现有 FastAPI | 完成 | `tools.router` 注册进 `main.py`，同一应用 |
| 真实文件读入 | 完成 | `.xlsx` / UTF-8(BOM) `.csv`；安全上传入口 |
| 模拟 BI 查询 | 完成 | 新表 `bi_financial_records` + 幂等 seed |
| 模拟 OA 持久化 | 完成 | 新表 `oa_reconciliation_records`，可读回、幂等 |
| 模拟数据与预期结果 | 完成 | `demo_data.py` 单一来源 + 7 个演示文件 |
| 测试 | 完成 | 111 通过 / 0 失败 / 0 跳过（见第 3 节） |
| 两条演示链 | 完成 | 已真实运行，见第 4 节 |
| 交接文档 | 完成 | `docs/RPA_TOOLS.md`、`docs/RPA_HANDOFF.md` |
| 旧 Agent 接入新工具 | **未完成（明确遗留）** | 旧 `/agent/*`、`/excel/*`、`/office/*` 仍用旧逻辑，见第 5、7 节 |
| 前端、大模型、真实 BI/OA、企业级部署 | 不在本次范围 | 未做，也不声称已完成 |

---

## 3. 实际测试记录

运行方式（项目根目录）：

```bash
D:\ENT207开发\.venv-backend-review\Scripts\python.exe -m pytest -q
D:\ENT207开发\.venv-backend-review\Scripts\python.exe -m pytest tests\test_api.py -q
```

实际结果：

```text
全量：      111 passed, 6 warnings in 6.67s      （失败 0，跳过 0）
原有测试：    5 passed, 6 warnings in 0.68s      （失败 0，跳过 0）
```

- 6 条 warning 的准确分类：2 条来自运行环境/依赖库（`fastapi.testclient` 的
  Starlette `httpx` 弃用提示、`starlette.testclient` 的 anyio `BlockingPortal`
  别名弃用提示），4 条是原代码中 Pydantic V2 的 `class Config` 弃用提示
  （tasks.py 第 30/56 行、users.py 第 30 行、office.py 第 34 行）。
  本次改动没有新增 warning。
  （更正说明：本文档最初写成“6 条全部是 Pydantic”，该说法不准确，见第一轮
  验收修复章节。）
- 测试全部使用临时数据库与临时目录（`tests/conftest.py` 在导入应用前设置
  `RPA_DATABASE_URL` 等环境变量），没有清空或依赖 `ai_rpa.db`。
- 测试使用真实 xlsx/csv 文件和真实 SQLite 会话；BI/OA 失败用“可恢复的故障注入”
  （monkeypatch session.query / commit）验证错误返回、回滚与重试，而不是只测顺利路径。
- 无 `pytest.skip`、无未运行项；没有修改 `backend-review/inspect_backend.py` 的历史观察。

---

## 4. 演示实际结果

### 4.1 seed（幂等）

```text
> python scripts/seed_demo_data.py
seed complete: 6 inserted, 0 updated, 6 total records
> python scripts/seed_demo_data.py
seed complete: 0 inserted, 6 updated, 6 total records
```

### 4.2 正常链 `python scripts/demo_normal_flow.py`

```text
NORMAL DEMO COMPLETED
task_id: 1, row_count: 3, valid_rows: 3, invalid_rows: 0, bi_records: 3
oa_records: OA-20260918-0001, OA-20260918-0002, OA-20260918-0003
source_unchanged: true
read_back: {supplier_id: SUP-001, order_id: ORD-1001, amount: 5000.0,
           date: 2026-09-18, payment_status: pending, record_status: matched}
```

任务 1 实际状态为 `completed`，3 条 `reconciliation_result` 落库
（`review_status=archived`），并写入了任务日志。

### 4.3 冲突链 `python scripts/demo_conflict_flow.py`

```text
CONFLICT DEMO COMPLETED (waiting for manual verification)
task_id: 2, total_rows: 3, valid_rows: 1, invalid_rows: 2
conflicts:
  row 2 SUP-001/ORD-1001 amount_mismatch: excel 5200.0, bi 5000.0, difference 200.0
        -> OA-20260918-0004, review_status=pending_review
  row 3 SUP-002/ORD-2001 payment_status_mismatch: excel 'paid', bi 'pending'
        -> OA-20260918-0005, review_status=pending_review
normal_result_recorded: false
source_unchanged: true
```

任务 2 实际状态为 `waiting_confirmation`，2 条 `reconciliation_exception`
以 `pending_review` 落库；没有写入正常结果记录，源文件未修改。

### 4.4 落库状态抽查（演示后）

```text
TASKS:      id=1 completed; id=2 waiting_confirmation
OA RECORDS: 3 × reconciliation_result/archived (task 1)
            2 × reconciliation_exception/pending_review (task 2)
TASK LOGS:  Demo Flow Start(running)
            OA Reconciliation Record Submitted(submitted) ×2
            Demo Flow Waiting Confirmation(waiting_confirmation)
```

演示在项目根目录生成了运行时文件 `ai_rpa.db`（默认数据库，正常运行产物）。
如需隔离演示，可先设置 `RPA_DATABASE_URL`、`RPA_UPLOAD_DIR` 等环境变量指向临时目录。

---

## 5. 技术与业务假设

技术假设：

- FastAPI + SQLAlchemy + SQLite + pandas + openpyxl 的原技术栈不变，未引入新依赖。
- 工具通过传入的 SQLAlchemy `Session` 工作；不传时自行创建并关闭会话。
- 金额在数据库中以两位小数字符串保存，比较与差额全部用 `Decimal`；
  JSON 输出转为数字，避免浮点参与业务判断。
- 幂等的最终保障是数据库唯一约束 `(task_id, operation_id)`，
  重复/并发冲突会回滚后按同一操作重查。
- 演示脚本使用默认 `ai_rpa.db`；测试强制使用临时数据库。

业务假设（均需组内确认，未写成均胜制度）：

- 7 个字段为演示必需字段；`supplier_id + order_id` 为业务组合键。
- 单一货币、两位小数、不做汇率换算；负数按演示规则视为非法。
- 日期统一 `YYYY-MM-DD`。
- `reconciliation_result` 仅当 `record_status=matched` 才允许归档；
  其它状态走 `reconciliation_exception` 且保持 `pending_review`。
- 不传 `operation_id` 时按内容哈希去重（相同内容视为重试）。
- `payment_status` / `record_status` 未做枚举强校验（只做非空与一致性比对），
  可选值仅作为文档参考。

---

## 6. 已知限制

1. 旧 Agent 与旧 Excel/OA 路由未切换到新工具（见第 7 节），当前是“四工具独立通过”，
   不是“完整软件已整合通过”。
2. 无真实 BI/OA、无企业数据、无外部系统调用；OA 只是本地归档表。
3. 没有完整身份认证与授权；本次未实现“人工确认后的业务更正与恢复”，也没有用
   `confirmed=true` 之类字段伪装授权。
4. `validate_data` 暂不比对 `supplier_name`，也没有枚举校验状态值。
5. CSV 仅支持 UTF-8 / UTF-8 BOM；GBK 等编码会报 `UNSUPPORTED_ENCODING`。`.xls` 明确不支持。
6. 无分页、并发压测、性能指标；上传文件只落磁盘，没有上传记录表。
7. 未在全新干净虚拟环境验证 `pip install`（本次使用审阅环境，借用预装包）。
8. 未做前端；未接入语言模型；未做 Docker/Redis/桌面 RPA 等，均为范围外。

---

## 7. 需要其他方向确认/接入的事项

后端方向：

1. 是否接受新增表 `bi_financial_records`、`oa_reconciliation_records` 及字段命名；
   若未来要并入正式表结构，需要提供不丢数据的迁移脚本（本次未改旧表）。
2. 旧 `/excel/validate`、`/agent/run`、`/office/rpa/fill` 如何切换到新工具；
   切换前请勿在答辩/演示材料中写“已整合”。
3. 任务状态由谁管理：工具已明确不碰全局状态；演示层使用
   `running → completed / waiting_confirmation / failed`，请确认与后端状态机一致。
4. `operation_id` 命名规范、是否需要服务端生成；上传接口是否需要入库与鉴权。
5. 人工确认后的“重新校验 / 更正金额 / 恢复执行”需要后端 + Agent 共同设计。

Agent 方向：

1. 通过 `execute_tool(tool, arguments)` 调用四个工具；
   成功/失败信封、业务异常（issues）与空结果的区分见 `docs/RPA_TOOLS.md`。
2. 冲突处理建议：检测到 `amount_mismatch` 等异常时调用
   `reconciliation_exception` 并保持 `pending_review`，不得直接归档为正常结果。
3. 不要依赖调用者自报的 `confirmed=true`；授权应绑定具体任务/记录并在后端保存。
4. 需要定义工具调用次数上限、失败重试策略和“记录未找到”的业务话术。

前端方向：

1. 上传用 `POST /tools/files`，把返回的 `file_path` 传给 `read_data_file`。
2. 展示 `issues[].row / field / type / message`，金额冲突展示
   `excel_amount / bi_amount / difference`（来源标签不能省略）。
3. 任务状态、错误码到界面提示的映射（区分业务异常与技术失败）。
4. 文件不存在、空结果、BI 查询失败、OA 写入失败是不同状态，需要不同提示。

全组：

1. 确认第 5 节的演示规则（负数、两位小数、状态取值、自动 operation_id 规则）。
2. 确认“提交异常记录 ≠ 人工批准”，前端文案不要写成“已处理完成”。
3. 演示材料中把“四工具独立可运行”和“整条产品链已打通”分开表述。

---

## 8. 复现命令汇总

```bash
cd ai-rpa-automation-backend

# 安装（普通 Python 3.12 虚拟环境）
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 初始化模拟 BI 数据（幂等）
python scripts/seed_demo_data.py

# 两条演示链
python scripts/demo_normal_flow.py
python scripts/demo_conflict_flow.py

# 测试
pytest                            # 全量 111 项
pytest tests/test_api.py          # 原有 5 项

# 启动服务与文档
uvicorn backend.app.main:app --reload
# http://127.0.0.1:8000/docs  -> RPA Tools 分组
```

---

# 第一轮验收修复（第二轮交付）

对应 `backend-review/acceptance-round1/` 的 F1—F7。本轮只做定向修复，没有重写项目、
没有改旧 Agent/前端/大模型/认证，也没有修改审阅者的独立测试与历史证据。上一轮的
111 项测试记录保持原样，本节记录修复后的实际状态。

## 1. 逐条对应

### F1 P1 重复金额表头被当作正常核对

- 根因：`validate_data` 没有读取 `read_data_file` 已经识别出的 `column_issues`，
  重复/空表头不会进入校验结果，正常编排因此按第一列完成归档。
- 修复：`backend/app/tools/validation.py` 把 `table.column_issues` 逐条转成
  文件级 `issues`（`duplicate_header` / `empty_header`），与 `missing_column`
  同级；正常链/冲突链都以完整 `issues` 判断是否暂停。
- 验证：`tests/test_acceptance_fixes.py::test_duplicate_required_header_is_reported`、
  `test_duplicate_amount_header_cannot_complete_normal_flow`、
  `test_blank_and_whitespace_headers_are_reported`；独立案例
  `test_duplicate_amount_header_is_not_clean`、
  `test_duplicate_amount_header_cannot_complete_normal_flow` 通过。
- 实际结果：重复金额表头返回 `issues` 含 `duplicate_header`；正常链任务转入
  `waiting_confirmation`，OA 归档记录为 0。

### F2 P1 自动重命名列碰撞并覆盖单元格

- 根因：`_build_columns` 只对同名表头追加序号，没有检查生成名是否已被使用，
  `amount, amount, amount__2` 变成 `amount, amount__2, amount__2`，字典键覆盖。
- 修复：`backend/app/tools/file_reader.py` 的 `_build_columns` 改为全局 `used`
  集合逐个分配唯一名字；发生碰撞时持续寻找未使用的 `__N` 后缀。每列按位置独立
  取值，不再经过可能覆盖的键。
- 验证：`test_header_collision_preserves_every_cell`（3 列 3 值全部保留）、
  `test_generated_header_name_collision_is_resolved`、
  `test_repeated_generated_names_stay_unique`；独立案例
  `test_renamed_header_collision_preserves_each_cell` 通过。
- 实际结果：列名 3 个互不相同，`records[0].data` 3 个键，值 `5000/5200/5300`
  一一对应。

### F3 P1 非法逗号金额静默变成合法金额

- 根因：`parse_amount` 对字符串先无条件 `replace(",", "")`，`50,00`、`5,,000`、
  `,5000` 都被拼成 `5000`。
- 修复：`backend/app/tools/rules.py` 新增严格金额文本正则，先整串校验格式再做
  Decimal 解析：允许纯数字或 1–3 位开头、每组恰好 3 位的千分位，最多两位小数；
  非法分组、空组、前后逗号、多余小数位一律拒绝。`validate_data` 与
  `submit_to_oa` 共用该规则。
- 验证：`test_malformed_amounts_are_rejected` 12 个参数案例、
  `test_legal_amounts_still_parse` 7 个合法案例、
  `test_oa_amount_check_uses_same_strict_rule`；独立 3 个参数案例通过。
- 实际结果：`1,250.50`、`1,000,000.01` 等仍正常；`50,00`、`5,,000`、`,5000`
  报 `invalid_amount`；OA 提交金额 `50,00` 返回 `INVALID_DATA`。

### F4 P2 BI 状态缺失时绕过状态核对

- 根因：比对条件 `excel_value and bi_value` 在 BI 状态缺失时为假，直接跳过且不报问题。
- 修复：`validation.py` 状态比对改为显式分支：Excel 有值而 BI 为空/空白 →
  `missing_reference_status`；BI 类型不是字符串 → `invalid_reference_status`；
  都有值且不同 → 原有 `*_mismatch`。
- 验证：`test_missing_reference_status_is_reported`（2 字段）、
  `test_blank_reference_status_is_reported`（2 字段）、
  `test_non_scalar_reference_status_is_reported`、
  `test_complete_reference_statuses_are_not_over_flagged`；独立 2 个字段案例通过。
- 实际结果：缺字段时 `invalid_rows=1` 并带明确问题类型；完整参考状态不会误报。

### F5 P2 格式错误被冲突流程标记为已完成

- 根因：冲突流程只把自己的 `CONFLICT_ISSUE_TYPES` 当异常，其他校验问题落入
  `conflicts=[]`，代码先写 `completed` 再抛错。
- 修复：`backend/app/services/demo_workflow.py` 把校验结果分成“可归档冲突”和
  “未归档问题”：
  - 只有不可归档问题时：`waiting_confirmation`，不写 OA 记录，摘要含
    `unarchived_issues`，并抛出 `DemoFlowError`；
  - 同时有两者时：归档冲突、整体保持 `waiting_confirmation`，摘要保留
    `unarchived_issues`，并抛出 `DemoFlowError`；
  - 只有冲突时：保持原行为（归档 + `waiting_confirmation`，退出 0）；
  - 真正无任何问题时：`completed` + `DemoFlowError`（演示期望输入不符）。
- 验证：`test_invalid_only_input_does_not_complete_conflict_flow`（amount/date 2 案例）、
  `test_mixed_conflict_and_format_errors_hold_for_review`；独立 2 个参数案例通过。
- 实际结果：非法金额/日期输入任务为 `waiting_confirmation`、OA 记录 0；
  混合输入 1 条冲突异常记录 + `waiting_confirmation`；摘要与状态一致。

### F6 P2 Excel 文本编号 NA 被变成空值

- 根因：XLSX 读取没有关闭 pandas 默认缺失值识别，文本 `NA` 被读成 NaN/None。
- 修复：`file_reader.py` 的 `excel.parse` 增加 `keep_default_na=False`；
  `_cell_value` 把真空字符串规范为 `null`，其他文本（含 `NA`、`N/A`）原样保留。
- 验证：`test_xlsx_text_placeholders_are_preserved`（NA/N/A/NULL/None/nan 5 案例）、
  `test_xlsx_real_empty_cell_stays_missing`；独立案例
  `test_xlsx_text_na_identifier_is_preserved` 通过。
- 实际结果：`NA` 等文本完整保留；真实空单元格仍为 `null` 并被校验报缺失。

### F7 P2 CSV 空白行导致错误定位偏移

- 根因：`pd.read_csv` 默认跳过空白行，而行号按“数据序号 + 2”生成，导致后续行号前移。
- 修复：`file_reader.py` 的 CSV 读取改用标准库 `csv.reader`，逐条记录物理起始行号
  （利用 `reader.line_num`）；空白行跳过但保留行号计数；带引号换行按起始行编号。
- 验证：`test_csv_blank_line_does_not_shift_issue_location`（问题行 = 3）、
  `test_multiple_csv_blank_lines_keep_line_numbers`（问题行 = 4）、
  `test_quoted_newline_keeps_physical_start_lines`（跨行记录后问题行 = 4）、
  `test_read_csv_reports_physical_row_numbers`；独立案例
  `test_csv_blank_line_does_not_shift_issue_location` 通过。
- 实际结果：CSV 中空白行不再造成行号偏移；引号内换行按记录起始物理行报告。

## 2. 新增回归测试

`tests/test_acceptance_fixes.py`，46 项，覆盖 F1—F7 及相邻边界（空白表头、
生成列名碰撞、反复生成名、合法/非法金额分组、空白与非标量参考状态、混合冲突
与格式问题、多空白行、引号换行、引号逗号字段、物理行号）。

- 未删改任何原有测试断言；修复后原 111 项全部保持通过（合计 157）。
- 未修改 `backend-review/acceptance-round1/` 下的任何文件；运行独立测试时该测试
  自身会在验收目录创建新的 `run-*` 临时目录（其设计行为），未触碰历史产物。

## 3. 实际运行命令与结果（第二轮）

说明：Windows 共享临时 pytest 目录存在访问限制，以下运行均使用工作区内全新
`--basetemp`；演示使用全新隔离 SQLite，项目 `ai_rpa.db` 未被修改。

```powershell
# 1) 项目全量测试（工作区新 basetemp）
$freshTestDir = Join-Path 'D:\ENT207开发\backend-review' ('fix-tests-' + [guid]::NewGuid().ToString('N'))
python -m pytest -q -p no:cacheprovider --basetemp $freshTestDir
# 实际：157 passed, 6 warnings（失败 0，跳过 0）

# 2) 独立 12 案例（不读团队 conftest，不修改其断言）
$freshAcceptanceDir = Join-Path 'D:\ENT207开发\backend-review' ('fix-acceptance-' + [guid]::NewGuid().ToString('N'))
python -m pytest -q -c 'D:\ENT207开发\backend-review\acceptance-round1\pytest.ini' `
  'D:\ENT207开发\backend-review\acceptance-round1\test_independent_acceptance.py' `
  --basetemp $freshAcceptanceDir
# 实际：12 passed in 2.76s（第一轮为 12 failed）

# 3) 隔离数据库演示（RPA_DATABASE_URL 指向全新临时目录）
#    本轮使用：C:\Users\33934\AppData\Local\Temp\opencode\fix-demo-8a2e309057d04afdb4b8850b85e68b07\demo.db
#    seed 两次：6 inserted / 0 updated / 6 total，再 0 / 6 / 6（幂等）
python scripts/seed_demo_data.py
python scripts/seed_demo_data.py
python scripts/demo_normal_flow.py
# 实际：退出 0；task 1 = completed；3 条 reconciliation_result/archived；
#       source_unchanged=true；read_back 与 BI 值一致
python scripts/demo_conflict_flow.py
# 实际：退出 0；task 2 = waiting_confirmation；2 条
#       reconciliation_exception/pending_review；excel 5200 vs bi 5000，
#       difference 200；unarchived_issues=[]；normal_result_recorded=false；
#       source_unchanged=true；running 任务 0
```

- `ai_rpa.db` 前后 SHA256：
  `BFE069EBBB03173D251E5A061053E1844C0EA4BE006602DB7E9D5AAD6A8DBFB3`（一致）。
- 6 条 warning 分类：2 条依赖/环境弃用（Starlette `httpx`、anyio
  `BlockingPortal` 别名），4 条原代码 Pydantic V2 `class Config` 弃用
  （tasks.py 2 处、users.py 1 处、office.py 1 处）。无新增 warning。

## 4. 修复后的边界声明（不变）

- 旧 `/agent`、`/excel`、`/office` 仍未调用新工具；前端、大模型、完整认证、
  人工确认后的更正与恢复仍未整合。
- 本次只改四工具、演示编排、相关测试与文档；未操作远程仓库，未改 Word/ZIP。
- 等待审阅者再次独立验收；本节结果不等于最终验收通过。

---

# 第二轮验收修复（第三轮交付）

对应 `backend-review/acceptance-round2/` 的 R2-1／R2-2（CSV 解析器替换引入的
结构校验回归）。上一轮 F1—F7 的修复全部保留，未重写工具、未扩大范围。历史记录
（111 项、第一轮修复章节）保持原样。

## 1. R2-1 P1 多于表头列数的数据被截断后正常归档

- 根因：`backend/app/tools/file_reader.py` 的 `_rows_to_table` 只按表头列数取值，
  CSV 数据行多出的第 8 个值被静默丢弃；校验因此看不到任何问题，正常编排按前 7 列
  归档为核对成功。
- 修复：`load_csv` 在转换之前检查每条数据行的值个数，多于表头列数时返回标准错误
  信封 `INVALID_CSV_STRUCTURE`，错误信息包含行号、实际值数和表头列数，明确说明
  拒绝截断/猜测；不修改任何源值。
- 语义（已写入 `docs/RPA_TOOLS.md`）：
  - 数据行 > 表头列数（含行尾多余逗号产生的空值）→ 拒绝读取；
  - 数据行 < 表头列数 → 缺失位置补 `null`，必要字段由 `validate_data` 报
    `missing_value`；
  - 列数一致 → 正常读取。
- 影响：正常链遇到结构错误时走读取失败路径，任务为 `failed`（不是 `completed`），
  OA 归档数为 0。
- 验证：`tests/test_csv_structure.py` 中
  `test_extra_data_cell_is_rejected`、`test_extra_cell_blocks_normal_flow`、
  `test_extra_cell_later_in_file_reports_its_row`、
  `test_extra_empty_cell_from_trailing_separator_is_rejected`、
  `test_validate_data_reports_extra_cell_as_error`、
  `test_short_row_is_padded_and_missing_required_fields_flagged`、
  `test_exact_width_rows_still_pass`；第二轮独立测试
  `test_malformed_csv_is_not_clean[extra_data_column]`、
  `test_extra_csv_cell_cannot_be_silently_dropped_then_archived` 通过。
- 实际结果：7 列表头 + 8 个值返回 `INVALID_CSV_STRUCTURE`（含 “row 2 / 8 / 7”）；
  后续行多值报对应行号；短行读取成功且校验报出缺失字段；正常 7 列数据不受影响。

## 2. R2-2 P2 未闭合引号被容错读取

- 根因：`csv.reader` 默认非严格模式，EOF 前未闭合的引号会被当作普通文本接受。
- 修复：`load_csv` 改用 `csv.reader(handle, strict=True)`，捕获 `csv.Error`
  并转换为 `CSV_PARSE_ERROR`，错误信息包含可取得的行位置；不补猜、不吞异常。
- 保持行为：引号内逗号、双引号转义（`""`）、引号内换行、UTF-8 BOM、空白行后的
  正确行号、文本标识符、表头碰撞防护全部保持（由原有与新增测试共同验证）。
- 验证：`test_unterminated_quote_is_a_tool_error`、
  `test_unterminated_quote_blocks_validation_and_normal_flow`、
  `test_unterminated_quote_mid_file_is_rejected`、
  `test_escaped_quotes_still_parse`、`test_quoted_comma_and_newline_still_parse`、
  `test_blank_lines_still_keep_row_numbers`；第二轮独立测试
  `test_malformed_csv_is_not_clean[unterminated_quote]` 通过。
- 实际结果：未闭合引号在读取、校验、正常编排三个阶段都返回错误，任务不为
  `completed`，OA 记录为 0；合法引号数据照常读取。

## 3. 新增回归测试

`tests/test_csv_structure.py`，13 项，覆盖两个根因及边界（后续行多值、尾随逗号、
短行补空、精确列宽、文件中段坏引号、合法转义/跨行/空行行号）。未删改任何原有
测试断言；上一轮 157 项全部保持通过。

未修改 `backend-review/acceptance-round2/`、`acceptance-round1/` 下的独立测试、
断言与历史证据；运行独立测试时测试自身会在其目录创建新的 `run-*` 临时目录
（设计行为），历史文件未被触碰。

## 4. 实际运行命令与结果（第三轮）

```powershell
# 1) 项目全量测试（工作区全新 basetemp）
$freshTestDir = Join-Path 'D:\ENT207开发\backend-review' ('r2-tests-' + [guid]::NewGuid().ToString('N'))
python -m pytest -q -p no:cacheprovider --basetemp $freshTestDir
# 实际：170 passed, 6 warnings（失败 0，跳过 0）

# 2) 第一轮独立 12 案例（保持通过）
$freshR1 = Join-Path 'D:\ENT207开发\backend-review' ('r2-r1-acceptance-' + [guid]::NewGuid().ToString('N'))
python -m pytest -q -c D:\ENT207开发\backend-review\acceptance-round1\pytest.ini `
  D:\ENT207开发\backend-review\acceptance-round1\test_independent_acceptance.py --basetemp $freshR1
# 实际：12 passed

# 3) 第二轮独立 3 案例（本轮修复目标）
$freshR2 = Join-Path 'D:\ENT207开发\backend-review' ('r2-acceptance-' + [guid]::NewGuid().ToString('N'))
python -m pytest -q -c D:\ENT207开发\backend-review\acceptance-round2\pytest.ini `
  D:\ENT207开发\backend-review\acceptance-round2\test_csv_structure_regressions.py --basetemp $freshR2
# 实际：3 passed（第二轮报告中为 3 failed）

# 4) 隔离数据库演示
#    DB: C:\Users\33934\AppData\Local\Temp\opencode\fix-r2-demo-2e0d68ee2a3a44119ec938cdf587b777\demo.db
python scripts/seed_demo_data.py   # 6 inserted / 0 updated / 6 total
python scripts/seed_demo_data.py   # 0 inserted / 6 updated / 6 total（幂等）
python scripts/demo_normal_flow.py
# 退出 0；task 1 completed；3 条 reconciliation_result/archived；source_unchanged=true
python scripts/demo_conflict_flow.py
# 退出 0；task 2 waiting_confirmation；2 条 pending_review；差额 200；
# unarchived_issues=[]；normal_result_recorded=false；running 任务 0
```

- `ai_rpa.db` 前后 SHA256 均为
  `BFE069EBBB03173D251E5A061053E1844C0EA4BE006602DB7E9D5AAD6A8DBFB3`（一致）。
- 6 条 warning 分类与上一轮相同（2 条 Starlette/anyio 环境弃用 + 4 条原代码
  Pydantic `class Config` 弃用），无新增。

## 5. 边界声明（不变）

- 上一轮 F1—F7 修复与四工具契约、OA 幂等、正常/冲突演示均保留。
- 旧 `/agent`、`/excel`、`/office` 仍未调用新工具；前端、大模型、完整认证、
  人工确认后的更正与恢复仍未整合，不借本次修复声称整套软件完成。
- 未操作远程仓库，未改原始 Word/ZIP。等待审阅者第三轮独立复验，本节结果不代表
  最终验收通过。
