from fastapi import FastAPI

from backend.app.database import Base, engine
from backend.app.routers import tasks
from backend.app.routers import excel
from backend.app.routers import bi
from backend.app.routers import agent
from backend.app.routers import users
from backend.app.routers import office
from backend.app.routers import system
from backend.app.routers import reports

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI-RPA Finance Automation Platform",
    version="1.0.0"
)

app.include_router(tasks.router)
app.include_router(excel.router)
app.include_router(bi.router)
app.include_router(agent.router)
app.include_router(users.router)
app.include_router(office.router)
app.include_router(system.router)
app.include_router(reports.router)


@app.get("/")
def root():
    return {
        "message": "AI-RPA Backend is running"
    }