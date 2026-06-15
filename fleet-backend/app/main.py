# # app/main.py
# import asyncio
# import sys
# from fastapi import FastAPI
# from contextlib import asynccontextmanager
# from app.services.mqtt_subscriber import mqtt_subscriber_task

# if sys.platform == "win32":
#     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# from app.api import routes_vehicles
# from app.api import routes_trips
# from app.api import routes_drivers
# from app.api import routes_config       # ← เพิ่มบรรทัดนี้

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     bg_task = asyncio.create_task(mqtt_subscriber_task())
#     print("🚀 ระบบดักฟังข้อมูลยานพาหนะ (MQTT Subscriber) เริ่มทำงานแล้ว")
#     yield
#     bg_task.cancel()
#     try:
#         await bg_task
#     except asyncio.CancelledError:
#         print("🛑 หยุดการทำงานระบบดักฟังเรียบร้อย (Gracefully Stopped)")

# app = FastAPI(
#     title="Kotchasaan Enterprise Fleet Telematics API",
#     version="1.1.0",
#     lifespan=lifespan
# )

# app.include_router(routes_vehicles.router)
# app.include_router(routes_trips.router)
# app.include_router(routes_drivers.router)
# app.include_router(routes_config.router)   # ← เพิ่มบรรทัดนี้

# @app.get("/")
# async def root():
#     return {
#         "status": "running",
#         "project": "Kotchasaan Fleet Telematics & Driver Behavior Monitoring System",
#         "compliance": "FDD v1.4 Satisfied"
#     }

# app/main.py
import asyncio
import sys
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from app.services.mqtt_subscriber import mqtt_subscriber_task

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.api import routes_vehicles
from app.api import routes_trips
from app.api import routes_drivers
from app.api import routes_config
from app.api import routes_reports     # ← ใหม่

@asynccontextmanager
async def lifespan(app: FastAPI):
    bg_task = asyncio.create_task(mqtt_subscriber_task())
    print("🚀 ระบบดักฟังข้อมูลยานพาหนะ (MQTT Subscriber) เริ่มทำงานแล้ว")
    yield
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        print("🛑 หยุดการทำงานระบบดักฟังเรียบร้อย (Gracefully Stopped)")

app = FastAPI(
    title="Kotchasaan Enterprise Fleet Telematics API",
    version="2.0.0",
    lifespan=lifespan
)

# Static files (API Tester UI)
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass

@app.get("/tester", include_in_schema=False)
async def api_tester():
    return FileResponse("static/fleet_api_tester.html")

# Routers
app.include_router(routes_vehicles.router)
app.include_router(routes_vehicles.fleet_router)  # SSE /fleet/live
app.include_router(routes_trips.router)
app.include_router(routes_drivers.router)
app.include_router(routes_config.router)
app.include_router(routes_reports.router)          # ← ใหม่

@app.get("/")
async def root():
    return {
        "status": "running",
        "project": "Kotchasaan Fleet Telematics & Driver Behavior Monitoring System",
        "compliance": "FDD v1.4 Full",
        "version": "2.0.0",
        "tester_ui": "/tester",
        "docs": "/docs"
    }