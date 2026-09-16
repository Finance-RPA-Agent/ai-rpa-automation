from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, text
from sqlalchemy.orm import relationship
from backend.app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(Text, nullable=False)
    status = Column(String, default="pending")
    filename = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    result = Column(Text, nullable=True)

    logs = relationship(
        "TaskLog",
        back_populates="task",
        cascade="all, delete-orphan"
    )

    exceptions = relationship(
        "ExcelException",
        back_populates="task",
        cascade="all, delete-orphan"
    )

    office_approvals = relationship(
        "OfficeApproval",
        back_populates="task",
        cascade="all, delete-orphan"
    )

    user = relationship(
        "User",
        back_populates="tasks"
    )


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    action = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    task = relationship(
        "Task",
        back_populates="logs"
    )


class ExcelException(Base):
    __tablename__ = "excel_exceptions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    filename = Column(String, nullable=False)
    row = Column(Integer, nullable=False)
    column = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    type = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    suggestion = Column(Text, nullable=False)
    status = Column(String, default="pending")
    resolution = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    task = relationship(
        "Task",
        back_populates="exceptions"
    )


class BIInventory(Base):
    __tablename__ = "bi_inventory"

    id = Column(Integer, primary_key=True, index=True)
    material_code = Column(String, nullable=False)
    warehouse = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)


class OfficeApproval(Base):
    __tablename__ = "office_approvals"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    title = Column(String, nullable=False)
    status = Column(String, default="pending")
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    task = relationship(
        "Task",
        back_populates="office_approvals"
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="user")
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    tasks = relationship(
        "Task",
        back_populates="user"
    )