# # app/api/routes_trips.py
# from fastapi import APIRouter, HTTPException, Body
# from typing import Dict, Any
# import asyncpg
# import json
# from app.config import settings

# router = APIRouter(prefix="/trips", tags=["Trips & Scoring"])

# async def get_db_connection():
#     return await asyncpg.connect(
#         user=settings.DB_USER,
#         password=settings.DB_PASS,
#         database=settings.DB_NAME,
#         host=settings.DB_HOST,
#         port=settings.DB_PORT
#     )

# # 🎯 1. ช่องทางให้หน้าบ้านดึงสูตรคะแนน/ตัวแปรปัจจุบัน ไปวาดปุ่มกดบนหน้าจอ UI
# @router.get("/scoring/config")
# async def get_current_scoring_config():
#     try:
#         conn = await get_db_connection()
#         row = await conn.fetchrow(
#             "SELECT * FROM scoring_config_cache WHERE is_active = TRUE LIMIT 1"
#         )
#         await conn.close()
#         if not row:
#             raise HTTPException(status_code=404, detail="ไม่พบ config")
#         return dict(row)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# # 🎯 2. ช่องทางรับข้อมูลเมื่อฝั่งหน้าบ้านกดเปลี่ยนเกณฑ์คะแนน/สวิตช์ข้อยกเว้น แล้วบันทึกส่งมา
# @router.post("/scoring/config")
# async def update_scoring_config(new_config: Dict[str, Any] = Body(...)):
#     """หน้าบ้านส่ง JSON ค่าตัวแปรสูตรคะแนนชุดใหม่มาบันทึกอัปเดตระบบหลังบ้าน"""
#     try:
#         conn = await get_db_connection()
#         config_json = json.dumps(new_config)
#         await conn.execute(
#             "INSERT INTO scoring_config (config_name, config_data, updated_at) VALUES ('default', $1, NOW()) "
#             "ON CONFLICT (config_name) DO UPDATE SET config_data = $1, updated_at = NOW()",
#             config_json
#         )
#         await conn.close()
#         return {"status": "success", "message": "อัปเดตเกณฑ์คะแนนและข้อยกเว้นในระบบสำเร็จ!"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# app/api/routes_trips.py
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import asyncpg
from app.config import settings

router = APIRouter(prefix="/trips", tags=["Trips & Scoring"])


async def get_db_connection():
    return await asyncpg.connect(
        user=settings.DB_USER,
        password=settings.DB_PASS,
        database=settings.DB_NAME,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
    )


# ============================================================
# GET /trips/{trip_id} — รายละเอียด trip + GPS track
# ============================================================
@router.get("/{trip_id}")
async def get_trip_detail(trip_id: int):
    """ดึงรายละเอียดทริปแบบเต็ม รวม GPS track"""
    try:
        conn = await get_db_connection()
        row = await conn.fetchrow("SELECT * FROM trip_logs WHERE id = $1", trip_id)
        if not row:
            raise HTTPException(status_code=404, detail="ไม่พบทริปนี้")

        # ดึง GPS track จาก telemetry_raw
        track = await conn.fetch(
            """
            SELECT ts, lat, lon, speed, heading, event
            FROM telemetry_raw
            WHERE device_id = $1 AND ts BETWEEN $2 AND $3
            ORDER BY ts ASC
        """,
            row["device_id"],
            row["trip_start"],
            row["trip_end"],
        )

        await conn.close()
        result = dict(row)
        result["gps_track_detail"] = [dict(t) for t in track]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# PATCH /trips/{trip_id}/mark-synced — mark synced_to_odoo
# ============================================================
@router.patch("/{trip_id}/mark-synced")
async def mark_trip_synced(trip_id: int):
    """อัปเดต synced_to_odoo = TRUE หลัง Odoo รับข้อมูลสำเร็จ"""
    try:
        conn = await get_db_connection()
        result = await conn.execute(
            "UPDATE trip_logs SET synced_to_odoo = TRUE WHERE id = $1", trip_id
        )
        await conn.close()
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="ไม่พบทริปนี้")
        return {"status": "success", "trip_id": trip_id, "synced_to_odoo": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
