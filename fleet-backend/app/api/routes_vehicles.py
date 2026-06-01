# # app/api/routes_vehicles.py
# from fastapi import APIRouter, HTTPException, Security
# from fastapi.security import APIKeyHeader
# from typing import List
# import asyncpg
# from app.config import settings

# router = APIRouter(prefix="/api/v1/vehicles", tags=["Vehicles"])

# # ============================================================
# # API Key Authentication
# # ============================================================
# API_KEY = "ktc-fleet-2026-secret"
# api_key_header = APIKeyHeader(name="APIKEY", auto_error=False)

# async def verify_api_key(api_key: str = Security(api_key_header)):
#     if api_key != API_KEY:
#         raise HTTPException(status_code=403, detail="API Key ไม่ถูกต้อง")
#     return api_key

# # ============================================================
# # DB Connection
# # ============================================================
# async def get_db_connection():
#     """เชื่อมต่อเข้าฐานข้อมูล TimescaleDB โดยใช้ค่าคอนฟิกจาก .env จริงของระบบ (Port 5434)"""
#     try:
#         return await asyncpg.connect(
#             user=settings.DB_USER,
#             password=settings.DB_PASS,
#             database=settings.DB_NAME,
#             host=settings.DB_HOST,
#             port=settings.DB_PORT
#         )
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"เชื่อมต่อฐานข้อมูลล้มเหลว: {str(e)}")

# # ============================================================
# # GET /api/v1/vehicles/{vehicle_id}/location
# # ============================================================
# @router.get("/{vehicle_id}/location")
# async def get_vehicle_location(
#     vehicle_id: int,
#     api_key: str = Security(verify_api_key)
# ):
#     """
#     GET /api/v1/vehicles/{id}/location
#     ดึงตำแหน่งและสถานะปัจจุบัน (ignition, speed) ของรถตาม vehicle_id
#     """
#     conn = await get_db_connection()
#     try:
#         # Step 1: หา device_id จาก vehicle_id ใน devices table
#         device = await conn.fetchrow(
#             "SELECT device_id FROM update_status WHERE vehicle_id = $1 LIMIT 1",
#             vehicle_id
#         )
#         device_id = device["device_id"]
        
#         if not device:
#             raise HTTPException(status_code=404, detail="ไม่พบอุปกรณ์ที่ผูกกับรถคันนี้")

#         device_id = device["id"]

#         # Step 2: ดึง telemetry ล่าสุดจาก device นั้น
#         row = await conn.fetchrow(
#             """
#             SELECT ts, lat, lon, speed, heading, ignition, event
#             FROM telemetry_raw
#             WHERE device_id = $1
#             ORDER BY ts DESC
#             LIMIT 1
#             """,
#             device_id
#         )
#         if not row:
#             raise HTTPException(status_code=404, detail="ยังไม่มีข้อมูล telemetry")

#         return {
#             "vehicle_id": vehicle_id,
#             "device_id": device_id,
#             "ts": row["ts"],
#             "lat": row["lat"],
#             "lon": row["lon"],
#             "speed": row["speed"],
#             "heading": row["heading"],
#             "ignition": row["ignition"],
#             "event": row["event"] or None,
#         }
#     finally:
#         await conn.close()

# # ============================================================
# # GET /api/v1/vehicles/{device_id}/trips
# # ============================================================
# @router.get("/{device_id}/trips")
# async def get_vehicle_trips(
#     device_id: str,
#     api_key: str = Security(verify_api_key)
# ):
#     """
#     ดึงรายงานสรุปผลการเดินทางและคะแนนความปลอดภัย (Safety Score) ย้อนหลัง
#     """
#     try:
#         conn = await get_db_connection()
#         rows = await conn.fetch(
#             "SELECT * FROM trip_logs WHERE device_id = $1 ORDER BY trip_start DESC",
#             device_id
#         )
#         await conn.close()
#         return [dict(r) for r in rows]
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# app/api/routes_vehicles.py
from fastapi import APIRouter, HTTPException, Security
from fastapi.security import APIKeyHeader
from typing import List
import asyncpg
from app.config import settings

router = APIRouter(prefix="/api/v1/vehicles", tags=["Vehicles"])

# ============================================================
# API Key Authentication
# ============================================================
API_KEY = "ktc-fleet-2026-secret"
api_key_header = APIKeyHeader(name="APIKEY", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="API Key ไม่ถูกต้อง")
    return api_key

# ============================================================
# DB Connection
# ============================================================
async def get_db_connection():
    """เชื่อมต่อเข้าฐานข้อมูล TimescaleDB โดยใช้ค่าคอนฟิกจาก .env จริงของระบบ (Port 5434)"""
    try:
        return await asyncpg.connect(
            user=settings.DB_USER,
            password=settings.DB_PASS,
            database=settings.DB_NAME,
            host=settings.DB_HOST,
            port=settings.DB_PORT
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เชื่อมต่อฐานข้อมูลล้มเหลว: {str(e)}")

# ============================================================
# GET /api/v1/vehicles/{vehicle_id}/location
# ============================================================
@router.get("/{vehicle_id}/location")
async def get_vehicle_location(
    vehicle_id: int,
    api_key: str = Security(verify_api_key)
):
    """
    GET /api/v1/vehicles/{id}/location
    ดึงตำแหน่งและสถานะปัจจุบัน (ignition, speed) ของรถตาม vehicle_id
    """
    conn = await get_db_connection()
    try:
        # Step 1: หา device_id จาก vehicle_id ในตาราง update_status
        device = await conn.fetchrow(
            "SELECT device_id FROM update_status WHERE vehicle_id = $1 LIMIT 1",
            vehicle_id
        )
        
        # [แก้ไขจุดพัง] ย้ายการเช็คค่าว่าง (None) ขึ้นมาทำเป็นอันดับแรกสุด ป้องกัน TypeError
        if not device:
            raise HTTPException(
                status_code=404, 
                detail=f"ไม่พบข้อมูลรถรหัส ID {vehicle_id} หรือยังไม่มีอุปกรณ์ผูกกับรถคันนี้"
            )

        # [แก้ไขจุดพัง] ดึงค่าโดยใช้คีย์ "device_id" ให้ถูกต้องตรงตามที่ SELECT มา และลบบรรทัด device["id"] ทิ้งไป
        device_id = device["device_id"]

        # Step 2: ดึง telemetry ล่าสุดจาก device นั้น
        row = await conn.fetchrow(
            """
            SELECT ts, lat, lon, speed, heading, ignition, event
            FROM telemetry_raw
            WHERE device_id = $1
            ORDER BY ts DESC
            LIMIT 1
            """,
            device_id
        )
        
        # ดักจับกรณีเจอบอร์ดรถแล้ว แต่ในตารางพิกัด telemetry_raw เครื่องนี้ยังไม่มีข้อมูล
        if not row:
            raise HTTPException(
                status_code=404, 
                detail=f"พบอุปกรณ์รหัส {device_id} แล้ว แต่ยังไม่มีประวัติการส่งพิกัดเข้ามาในตาราง telemetry_raw"
            )

        return {
            "vehicle_id": vehicle_id,
            "device_id": device_id,
            "ts": row["ts"],
            "lat": row["lat"],
            "lon": row["lon"],
            "speed": row["speed"],
            "heading": row["heading"],
            "ignition": row["ignition"],
            "event": row["event"] or None,
        }
        
    except HTTPException as http_ex:
        # ปล่อยให้ HTTPException ทำงานปกติเพื่อให้ฝั่งหน้าเว็บเห็น Error โค้ดสุภาพ (404)
        raise http_ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    finally:
        await conn.close()

# ============================================================
# GET /api/v1/vehicles/{device_id}/trips
# ============================================================
@router.get("/{device_id}/trips")
async def get_vehicle_trips(
    device_id: str,
    api_key: str = Security(verify_api_key)
):
    """
    ดึงรายงานสรุปผลการเดินทางและคะแนนความปลอดภัย (Safety Score) ย้อนหลัง
    """
    conn = await get_db_connection()
    try:
        rows = await conn.fetch(
            "SELECT * FROM trip_logs WHERE device_id = $1 ORDER BY trip_start DESC",
            device_id
        )
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()