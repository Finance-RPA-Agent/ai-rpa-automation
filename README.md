# AI-RPA Finance Automation Platform

## 1. Project Overview

This project is an AI-agent-based finance cross-system data processing and workflow automation platform.

The backend is developed using FastAPI and provides task management, Excel processing, BI data queries, exception detection, human confirmation, Office Automation approval, user management, operation logs, and AI Agent workflow orchestration.

The system demonstrates a representative finance automation workflow:

Natural Language Task  
→ AI Agent  
→ Excel Validation  
→ BI Data Query  
→ Exception Detection  
→ Human Confirmation  
→ Office Automation Approval  
→ Final Result Generation

The project is designed as an MVP for finance workflow automation.

---

## 2. Backend Technology Stack

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- SQLite
- Pandas
- OpenPyXL
- Pydantic
- pwdlib / Argon2
- Pytest
- HTTPX

---

## 3. Project Structure

```text
ai-rpa-automation-main/
│
├── backend/
│   └── app/
│       ├── routers/
│       │   ├── agent.py
│       │   ├── bi.py
│       │   ├── excel.py
│       │   ├── office.py
│       │   ├── system.py
│       │   ├── tasks.py
│       │   └── users.py
│       │
│       ├── database.py
│       ├── main.py
│       └── models.py
│
├── uploads/
├── outputs/
├── tests/
│   └── test_api.py
│
├── ai_rpa.db
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 4. Core Backend Functions

### User Management

The backend provides basic user management functions:

- User registration
- User login
- User information query
- User list query
- Password hashing using Argon2

---

### Task Management

Tasks represent finance automation workflows.

Supported functions include:

- Create task
- Query task
- Query task list
- Associate task with user
- Store task execution status
- Store final task result
- Store operation logs

Task status can include:

```text
pending
running
waiting_confirmation
completed
failed
```

---

### Excel Processing

The Excel connector supports:

- Excel file upload
- Excel reading
- Data validation
- Exception detection
- Human exception handling
- Excel value modification
- Processed Excel output

The system currently detects three predefined exception types:

```text
missing_value
negative_value
duplicate_value
```

Detected exceptions are stored in the database.

---

### Human Confirmation

When Excel exceptions are detected, the Agent pauses the workflow.

The task status becomes:

```text
waiting_confirmation
```

A user can then review each exception and perform actions such as:

```text
approve
modify
reject
```

After all exceptions are handled, the Agent can continue the workflow.

---

### BI Connector

The BI connector is implemented using simulated inventory data stored in SQLite.

The Agent can query inventory information including:

- Material code
- Warehouse
- Quantity

This simulates integration with an enterprise BI system.

---

### Office Automation

The Office Automation module simulates an enterprise approval workflow.

The backend supports:

- Create approval request
- Query approval request
- Approve request
- Reject request

The Agent pauses until the approval process has been completed.

---

## 5. AI Agent Workflow

The Agent converts a task description into structured execution steps.

Example workflow:

```text
excel_validate
bi_check
exception_handle
office_approval
generate_result
```

A complete task follows this process:

```text
User creates task
        ↓
Agent parses task
        ↓
Excel validation
        ↓
BI inventory query
        ↓
Exception detection
        ↓
Human confirmation
        ↓
Excel modification if required
        ↓
Office approval
        ↓
Final result generation
        ↓
Task completed
```

The Agent does not automatically execute uncertain or high-risk operations.

When human confirmation is required, execution pauses until the user provides a decision.

---

## 6. Final Result

After the workflow is successfully completed, the system stores a structured JSON result.

The result can contain:

```json
{
    "task_id": 1,
    "user_id": 1,
    "status": "completed",
    "filename": "example.xlsx",
    "original_file": "uploads/example.xlsx",
    "processed_file": "outputs/processed_example.xlsx",
    "bi_records": 5,
    "exceptions_total": 3,
    "exceptions_approved": 1,
    "exceptions_modified": 1,
    "exceptions_rejected": 1,
    "exceptions_pending": 0,
    "office_approval": {
        "approval_id": 1,
        "status": "approved"
    }
}
```

---

## 7. System Status

The backend provides a system status API:

```text
GET /system/status
```

It provides information about:

- Users
- Tasks
- Task status
- Excel exceptions
- BI inventory records
- Office approvals
- Connector availability

The three main connectors are:

```text
Excel
BI
Office Automation
```

---

## 8. API Modules

The backend API is divided into the following modules:

```text
Agent
Tasks
Excel
BI
Office
Users
System
```

Interactive API documentation is provided automatically by FastAPI Swagger UI.

After starting the backend, open:

```text
http://127.0.0.1:8000/docs
```

---

## 9. Installation

Create and activate a Python virtual environment.

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 10. Run the Backend

From the project root directory, run:

```bash
uvicorn backend.app.main:app --reload
```

The backend server will run at:

```text
http://127.0.0.1:8000
```

Swagger API documentation:

```text
http://127.0.0.1:8000/docs
```

---

## 11. Testing

Automated API tests are stored in:

```text
tests/test_api.py
```

Run the tests using:

```bash
pytest
```

The tests cover basic backend availability and important API behaviour.

---

## 12. Database

The project currently uses SQLite.

Database file:

```text
ai_rpa.db
```

Main database entities include:

- User
- Task
- TaskLog
- ExcelException
- BIInventory
- OfficeApproval

---

## 13. Safety and Control

The platform follows a human-in-the-loop workflow.

The Agent can automate data processing and system coordination, but uncertain or sensitive operations can require human confirmation.

The MVP does not perform real financial payments, bank transfers, or final financial approvals.

---

## 14. MVP Scope

The current MVP demonstrates one representative finance workflow using:

- One AI Agent workflow
- Excel connector
- BI connector
- Office Automation connector
- Database persistence
- Exception detection
- Human confirmation
- Task management
- User management
- Operation logs
- Final result generation

The system is designed to demonstrate cross-system finance workflow automation rather than replace a complete enterprise RPA or financial platform.