from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.db.mongodb import connect_to_mongo, close_mongo_connection
from app.routes import auth, user, company, batch, quarter, session_template, calendar_events, settings, gpt, dashboard, notification, orm

from app.services.reminder_scheduler import start_reminder_scheduler
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    try:
        await connect_to_mongo()
        # Start the background scheduler
        asyncio.create_task(start_reminder_scheduler())
    except Exception as e:
        print(f"CRITICAL: Application started but background tasks failed: {e}")
    yield
    # Shutdown logic
    await close_mongo_connection()

app = FastAPI(title="Business Coaching ERP", lifespan=lifespan)

# Global exception handlers for standard JSON responses on errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": origin if origin else "*"}
    )

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(user.router, prefix="/api")
app.include_router(company.router, prefix="/api")
app.include_router(batch.router, prefix="/api")
app.include_router(quarter.router, prefix="/api")
app.include_router(session_template.router, prefix="/api")
app.include_router(calendar_events.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(gpt.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(notification.router, prefix="/api")
app.include_router(orm.router, prefix="/api")

@app.get("/")
async def root():
    return {"status": "success", "message": "Business Coaching ERP API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
