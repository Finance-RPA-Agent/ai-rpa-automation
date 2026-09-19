# Week 2 当前后端技术差异审计

审计日期：2026-09-17。固定场景：供应商财务数据核对与异常处理。

结论：当前 backend 是可以开展本地核验的规则式原型，不能据此宣称已经实现供应商核对 MVP 或完整 LLM Agent。Week 2 应记录差异、确认共享字段/工具/状态语义，并验证独立数据契约；不需要本周重构后端。本文不授权后续正式开发。

## 1. 输入与仓库身份

- 本地仓库：`C:\Users\Administrator\Desktop\课件\大三上\ENT207\repos\ai-rpa-automation`。
- 来源：`https://github.com/Finance-RPA-Agent/ai-rpa-automation.git`；clone、`fetch --all` 已实际完成。
- 已看到 `origin/main`、`origin/frontend`、`origin/backend`、`origin/agent`、`origin/rpa`。
- 审计基准：`origin/backend`，HEAD `6be9dc0d20a18d44d7f4f4343e4260dd00eb7b99`。
- 工作分支：`week2-agent-validation`，从 `origin/backend` 创建，无上游；不 commit、不 push、不 PR、不合并。
- `origin/agent` 当前 HEAD `d6a5de788540547f9401ab902c205882248a12d4`，树中仅 `.gitignore` 和 `README.md`；此次未在它上面开发。
- clone 后、创建工作分支后的 `git status --short` 均为空。仓库未发现 `AGENTS.md`。
- 依据：ENT207 `项目/` 下的 V0.3 计划书、V3.1 Week 2 执行方案及 AI Agent 交付包 V1。完整只读提取 OOXML 正文；未修改原文档。
- V0.3 SHA256：`96458a8f1d2a05e43d63734991a0a7f02f6bda32d115925e523ccc9c8dde1f86`。
- V3.1 SHA256：`06b1c9199d0bfcef6640cd965dbc41d175e07b1f8877c2364d028286c31468d3`。

## 2. 结论标签与核验边界

- **代码已实现**：从当前源代码直接确认的结构或分支；不等于该业务路径已执行成功。
- **仅设计**：计划书/交付包要求或本文建议，尚未接入运行主链路。
- **本机已验证**：本次实际 Git 命令、依赖安装、pytest 的结果；测试详情见 `LOCAL_TEST_RESULT.md`。
- **未验证**：未运行的业务路径、真实企业接入、权限安全、模型效果与完整供应商流程。

本文逐文件差异来自静态代码审计。现有五个 API 冒烟测试不覆盖人工确认、业务字段、异常核对或 Agent 成功主链路；新增契约测试仅验证 Python 数据校验。任何测试通过均不能升级为上述业务能力已经验证。

## 3. 基线对照

| 基线 | 当前代码证据 | 判断 | Week 2 处理 |
|---|---|---|---|
| 六状态 pending/running/waiting_confirmation/completed/failed/cancelled | agent 写入前四种；system 统计前五种；tasks 接受任意字符串 | 部分代码已实现；failed 没有明确失败落库链路，cancelled 没有取消处理 | 文档和独立 schema 对齐；原路由本周不改 |
| supplier_id/supplier_name/order_id/amount/date/payment_status/record_status | BIInventory 为 material_code/warehouse/quantity；OA/报告为报销语义 | 偏离固定场景；最终字段仍未确认 | 仅标记，等后端牵头共享字段表，禁止自行迁移 |
| 必填缺失、格式、金额/记录冲突 | Excel 现有 missing_value/negative_value/duplicate_value | 空值检查部分覆盖；未按必填表检查缺列；格式与跨源金额冲突未实现 | 确认预期规则与共享样例；不补业务实现 |
| 业务异常与工具失败分开 | ExcelException 无统一类别；BI 空列表当 success；工具读写异常没有统一结果封装 | 未完整实现 | 独立 ExceptionInfo 区分类别；正式工具错误协议留后续 |
| 确认后恢复 running 并记录恢复事件 | handle_exception 只改异常；run 每次写 running 和 Agent Start | 显式恢复事件缺失；需要再次调用 run，且从头遍历步骤 | 本周记录差异，后续做恢复/幂等/重校验 |
| Agent 决策，工具执行 | agent.py 内直接 pandas 校验、查 BI 数据库、创建 OA 审批 | 职责混合且复制 Excel 执行逻辑 | 不重构；仅独立契约预研 |
| 禁真实付款/转账/最终财务审批/删除关键记录 | 未发现此类真实连接或执行路由；OfficeApproval 为本地模拟 | 没有真实执行能力；不代表统一权限防护已验证 | 文档明确禁止；候选工具/确认动作不包含这些能力 |

## 4. 逐文件审计

### backend/app/routers/agent.py

- **当前做了什么（代码已实现）**：`parse_description`（40–57 行）根据 Excel/表格、BI/库存、异常关键词生成步骤，并无条件追加 office_approval、generate_result；`/parse` 保存 Task；`/run` 同步遍历步骤、写 TaskLog、读 Excel、查库存、创建/等待本地 OA 审批并保存 JSON 结果。
- **一致**：保存 task_id/文件/用户上下文；有 pending/running/waiting_confirmation/completed；等待人工处理异常和模拟审批；completed 分支返回已保存结果，避免重复执行已完成任务。
- **偏离**：不是 LLM 规划且不使用 allowed_tools；176–235 行复制 excel.py 校验；319–331 行直接查 BIInventory，未匹配供应商订单或比较金额；402 行起直接管理 OA 数据；缺 failed/cancelled 执行处理。139–150 行先提交 running，再可能抛缺文件错误；没有统一工具失败结果/失败日志，任务可能留在 running。等待后再调用 run 仍记录 Agent Start，未记录专用恢复事件或保存执行游标。Excel 修改产物在 outputs，但重新校验仍读 uploads；已存在异常时不重新保存新的检测结果。没有文件名时，即使计划没有 Excel 步骤，最终 `os.path.join('uploads', task.filename)` 也存在 TypeError 风险（静态推断，未实际触发）。
- **Week 2 是否必须改**：运行代码不必本周改；必须在设计记录中澄清“规则原型、尚非供应商流程”，确认恢复/失败/取消语义。本次只新增不被路由引用的 schema。
- **Week 4+**：在后续授权下，将规划/判定与工具执行分离；使用确认后的统一工具定义；加入受约束模型输出、错误协议、恢复游标、重校验与幂等。模型评估另行安排。

### backend/app/models.py

- **当前做了什么（代码已实现）**：定义 Task、TaskLog、ExcelException、BIInventory、OfficeApproval、User；Task 关联日志/异常/审批/用户，保存文件及文本结果。
- **一致**：已有任务、异常、操作日志、模拟确认对象的持久化基础；Task 默认 pending；日志有时间戳。
- **偏离**：Task.status 为不受约束 String；BIInventory（79–85 行）只有库存字段，未定义供应商共享字段；ExcelException.type 无业务/工具失败分类。未见独立工作流步骤、工具执行结果或具备 task/record/field/原值/拟值/动作/用户选择完整绑定的确认记录。cascade delete-orphan 是 ORM 配置，不是已经存在删除财务记录的 API。
- **Week 2 是否必须改**：不改实体/数据库；必须由后端确认字段和对象草案。独立契约不生成 supplier 数据表、不改库存实体。
- **Week 4+**：依据冻结字段做迁移与异常/确认/步骤/结果模型；严格状态与事件约束；操作记录和访问控制。

### backend/app/routers/tasks.py

- **当前做了什么（代码已实现）**：创建/查询 Task，更新状态/结果，写/查询日志，处理 Excel 异常；`modify_excel_file` 用 openpyxl 修改并保存 outputs；另提供库存 BI 查询。
- **一致**：处理异常时按 task_id + exception_id 查找；approve/reject/modify 有操作校验与日志；modify 需要 new_value；存在用户归属字段。
- **偏离**：42–43、225 行接受任意状态，不检查六状态或合法转移，也不记录状态更新事件。307–407 行的异常确认不恢复 Task.running，不记录恢复事件；未验证确认者身份/动作范围/关键字段风险，修改后没有业务重校验。reject 标成已处理，后续 pending_count 不包含它，尚无拒绝关键修改后的统一策略。410 行起仍查询库存，零记录返回 success；工具修改失败与业务异常缺统一区分。user_id 数据字段不等于身份鉴权。
- **Week 2 是否必须改**：不改现有接口；本周明确状态、恢复、确认绑定和拒绝/取消预期，待后端负责人确认。
- **Week 4+**：安全工具层承接 Excel 真正修改；冻结字段后校验参数和授权；正式恢复事件、取消处理与状态转移保护。

### backend/app/routers/excel.py

- **当前做了什么（代码已实现）**：上传 .xlsx/.xls、读 pandas，返回行列；validate 将空值/负数/按列重复存成 ExcelException；按 task 查询异常。
- **一致**：真实本地文件读取与规则检测，不靠模型声称成功；异常包含行、列、值、原因和建议；缺任务返回 404。
- **偏离**：检查所有现有单元格空值，不检查共享必填字段缺列，也不区分可空字段；所有列均检查重复，供应商/状态等可合法重复值可能误报。没有日期/金额格式规则、Excel/BI 金额或记录冲突比较。36、74 行未包装读取失败；文件无法读取与数据异常未形成统一协议。validate 不把 filename 绑定到 Task，也不改变 Task 状态。原始上传名直接 join，尚无安全路径检查；重复上传可能覆盖同名文件。允许 .xls，但 requirements 不含通常用于旧格式读取的 xlrd，实际 .xls 读取未验证。
- **Week 2 是否必须改**：不改业务检测/文件接口；文档清楚标记缺失覆盖，先对齐后端共享样例。
- **Week 4+**：依照冻结字段实施必填/格式规则和跨源核对；统一读取失败返回、文件身份与路径校验、异常重检。保留工具层承担执行。

### backend/app/routers/bi.py

- **当前做了什么（代码已实现）**：`GET /bi/inventory` 查询 SQLite BIInventory，可按 material_code/warehouse 过滤，返回 success/count/data。
- **一致**：可运行的模拟查询层，未接真实企业 BI；执行与返回结构已有基础。
- **偏离**：库存键与供应商/订单/金额/状态基线不一致；零匹配仍是 success/空列表，尚无 record_not_found 业务异常。数据库错误缺结构化 tool_failure；没有 Agent 所需的比较事实。
- **Week 2 是否必须改**：不改库存字段或另建冲突样例；标记待后端/RPA 共同确认查询键与预期返回。
- **Week 4+**：冻结字段后建立供应商模拟查询及核对接口，区分正常/无记录/工具错误；不要求真实企业接入。

### backend/app/routers/office.py

- **当前做了什么（代码已实现）**：本地模拟审批创建、查询、pending/approved/rejected 更新；build_oa_form 汇总任务/文件/异常数量；`/rpa/fill` 在无 pending 异常时创建模拟审批并写日志，`/rpa/form` 返回构造的表单。
- **一致**：无真实 OA 接入；先阻止未处理异常的模拟表单填充；有审批状态校验、日志和时间戳；不涉及真实付款或银行转账。
- **偏离**：89 行 form_type 是 finance_reimbursement_review，253 行标题是报销审核；不符合供应商异常事项主线。`form_filled` 代表构造返回/本地记录，不是已操作真实企业 UI。模拟 approval 更新不恢复 Task.running；无身份/确认范围约束或权限复查。Agent 内部另外创建审批，存在重复职责，Agent 取 first 而 office 按最新取值。缺 OA 工具失败与“核对结果保留、写入未完成”的协议。
- **Week 2 是否必须改**：本周不改审批模块；文档明确“模拟业务确认、不是最终财务审批”，由三方确认 OA 允许动作。
- **Week 4+**：转换为经共同批准的供应商异常/处理记录语义，统一执行入口、确认绑定、失败返回与写入结果保存。

### backend/app/routers/reports.py

- **当前做了什么（代码已实现）**：按 task 读取异常、最新审批、按 ID 排序的日志、已存结果和存在的输出路径，返回审计 JSON。
- **一致**：汇总异常原值/原因/处理结果和带时间戳的操作日志；保存结果 JSON 解析失败可退回原文本。
- **偏离**：127 行 report_type 为 finance_reimbursement_audit_report；不含供应商/订单的核对事实、字段冲突及工具失败独立结构；没有区分“核对完成”和“OA 写入未完成”。无完成状态门槛，任意任务状态可返回报告；success=True 是请求成功，不等于流程完成。Agent/本文件审批取值策略也不一致。
- **Week 2 是否必须改**：不改报表代码；在页面/设计中区分请求成功、报告生成与业务完成。
- **Week 4+**：共享字段确认后生成供应商结果结构、部分成功/写入失败信息和统一审计事件。

### backend/app/routers/system.py

- **当前做了什么（代码已实现）**：统计用户/任务/Excel 异常/库存/审批数量；任务按五个字符串状态计数；返回 online 和固定 available 连接器标签。
- **一致**：包括 pending/running/waiting_confirmation/completed/failed 统计，适合原型工作台展示。
- **偏离**：缺 cancelled 统计；failed 计数不代表 Agent 已实现失败落库；任意其他状态可能只计入 total。online/available 是代码固定值，不是实际 BI/OA/Excel 连接自检，更不是企业系统在线证据。
- **Week 2 是否必须改**：本周不改接口；设计统一第六状态，前端不把这些标签解释为真实系统健康验证。
- **Week 4+**：取消统计、状态一致性与按工具结果更新健康信息；保留模拟环境标记。

### tests/test_api.py 与 pytest.ini

- **当前做了什么（代码已实现）**：pytest.ini 配置仓库 pythonpath 和 tests 路径；现有五个测试检查根接口、system 字段、用户列表及不存在 task/user 的 404。
- **一致**：真实 TestClient 调用，明确断言状态码与响应；属于可执行冒烟测试。
- **偏离**：没有供应商正常/缺必填/格式/金额冲突共享样例；没有确认恢复、拒绝/取消、BI 无记录/失败、OA 写入失败测试。导入 main 会建 SQLite 表，缺隔离 fixture；硬编码不存在的 999999 ID 假定测试库为空。测试通过不能证明完整 Agent 或安全控制。
- **Week 2 是否必须改**：现有测试保持原样；实际运行并如实报告。新增 `tests/test_agent_contract.py` 仅验证契约，不虚构供应商业务通过结果。
- **Week 4+**：在冻结样例后补关键业务路径测试、临时数据库/文件 fixture、恢复事件与失败保留结果断言。

### backend/app/database.py 与 backend/app/main.py

- **当前做了什么（代码已实现）**：SQLite URL 为 `sqlite:///./ai_rpa.db`；main 导入时执行 create_all 并注册各 router。
- **一致**：后端集中注册接口，数据由后端持久化；无模型连接。
- **偏离**：数据库路径依赖进程工作目录，导入就产生运行文件；没有测试环境配置或运行数据隔离。当前没有企业系统安全部署验证。
- **Week 2 是否必须改**：不改。此次 pytest 从仓库外专用工作目录运行，保留原始测试文件并隔离数据库产物。
- **Week 4+**：在后续授权下加入可配置数据库、应用启动生命周期、测试依赖替换与必要迁移。

### requirements.txt、.gitignore 与 README.md

- **当前做了什么（代码已实现/文档已有）**：依赖列出 FastAPI、uvicorn、SQLAlchemy、pandas、openpyxl、multipart、pwdlib[argon2]、pytest、httpx；.gitignore 忽略 .venv/缓存、ai_rpa.db、uploads/outputs；README 描述库存/报销示例与五状态。
- **一致**：单一依赖文件；敏感环境与常见运行文件已有忽略规则；README 声明不进行真实付款/转账/最终财务审批。
- **偏离**：依赖未固定版本，Pydantic 是 FastAPI 间接依赖；独立 schema 使用 Pydantic v2，尚无跨版本承诺。README 五状态遗漏 cancelled，库存示例也不等于供应商方案。忽略 ai_rpa.db 不覆盖任意命名数据库；不得依靠 ignore 宣称不会提交敏感文件。
- **Week 2 是否必须改**：本次不改上述文件；记录本机实际安装版本，明确只是当前组合验证。环境和运行产物放在仓库外，Git 无提交行为。
- **Week 4+**：团队统一依赖版本/直接依赖与数据忽略策略；经共同确认更新 README 的场景与能力描述。

## 5. 本次最小预研范围

只新增 `backend/app/schemas/agent_contract.py` 与 `tests/test_agent_contract.py`；未修改或导入运行主链路。

- **代码已实现**：AgentInput、AgentOutput、ExceptionInfo、ConfirmationScope，六状态 Literal，候选工具 Literal 和去重校验，严格类型与多余字段拒绝，递归拒绝明确的 Python/Shell/SQL/浏览器脚本载荷字段。
- **代码已实现**：`validate_agent_output(input, payload)` 使用输入的 allowed_tools 校验 next_tool；输出不接受自行提供白名单。等待确认不选择工具，确认 scope 绑定 task；终止状态输入不选择下一工具。此校验是数据关系检查，不执行真正状态转移。
- **仅设计/待确认**：read_excel/query_bi/validate_fields/update_oa/create_exception/generate_report 是交付包及方案能力的候选名称，不是正式共享工具表，不是对现有 endpoint 的可执行映射。
- **仅设计/待确认**：ConfirmationScope action 仅为 modify_field/update_record/create_exception 预研；不允许付款/转账/最终审批/删除动作枚举。业务字段通过通用字段名称表达，不冻结 supplier 字段、不修改库存/报销实体。
- **未验证/尚未实现**：按工具的参数规则、金额/日期语义校验、真正权限判定、已批准动作范围检查、确认后恢复与事件持久化、业务状态机、数据库迁移、文件安全、模型结构化输出能力和端到端供应商业务。
- **限制**：通用上下文/参数允许 JSON 数据；脚本键黑名单和 extra=forbid 不是代码沙箱，不能证明自然语言字符串中的任意意图被阻止。确认动作枚举也不等于后端已经防止恶意写入；调用工具前仍必须执行后端/RPA 权限与参数校验。

## 6. 后续交接

Week 2 优先由后端方向牵头，与 AI/RPA/产品共同确认唯一的字段表、5–10 条共享模拟样例及预期结果、唯一工具定义和六状态事件表。记录此原型与基线的差异，用于 Week 3 可点击原型的真实能力说明。字段未确认前不迁移 inventory/reimbursement；正式运行链路修改留至 Week 4+ 且需后续授权。

测试是否通过及原始摘要只以 `LOCAL_TEST_RESULT.md` 的实际运行记录为准。此次无 Ollama 接入、Qwen 下载、外部模型调用、真实企业连接、提交、推送或合并。
