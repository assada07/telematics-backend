# # app/api/routes_config.py
# from fastapi import APIRouter, HTTPException, Security
# from fastapi.security import APIKeyHeader
# from pydantic import BaseModel
# from typing import List
# import asyncpg
# from app.config import settings

# router = APIRouter(prefix="/api/v1", tags=["Config"])

# API_KEY = "ktc-fleet-2026-secret"
# api_key_header = APIKeyHeader(name="APIKEY", auto_error=False)

# async def verify_api_key(api_key: str = Security(api_key_header)):
#     if api_key != API_KEY:
#         raise HTTPException(status_code=403, detail="API Key ไม่ถูกต้อง")
#     return api_key

# async def get_db_connection():
#     return await asyncpg.connect(
#         user=settings.DB_USER,
#         password=settings.DB_PASS,
#         database=settings.DB_NAME,
#         host=settings.DB_HOST,
#         port=settings.DB_PORT
#     )

# class RegisterDeviceRequest(BaseModel):
#     device_id:   str
#     device_name: str
#     vehicle_id:  int

# @router.get("/config_device")
# async def get_config_device(
#     device_id:   str = "",
#     device_name: str = "",
#     api_key: str = Security(verify_api_key)
# ):
#     conn = await get_db_connection()
#     try:
#         row = await conn.fetchrow(
#             "SELECT vehicle_id, device_id, date_update_latest FROM update_status WHERE device_id = $1 LIMIT 1",
#             device_id
#         )
#         if row:
#             return {"found": True, "device_id": row["device_id"], "device_name": device_name, "vehicle_id": row["vehicle_id"], "date_update_latest": row["date_update_latest"]}
#         else:
#             return {"found": False, "device_id": "", "device_name": "", "vehicle_id": None, "date_update_latest": None}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         await conn.close()

# @router.post("/config_device/register")
# async def register_device(body: RegisterDeviceRequest, api_key: str = Security(verify_api_key)):
#     conn = await get_db_connection()
#     try:
#         await conn.execute("INSERT INTO update_status (vehicle_id, device_id, date_update_latest) VALUES ($1, $2, NOW()) ON CONFLICT (vehicle_id, device_id) DO UPDATE SET date_update_latest = NOW()", body.vehicle_id, body.device_id)
#         await conn.execute("INSERT INTO devices (id, vehicle_id, active) VALUES ($1, $2, true) ON CONFLICT (id) DO UPDATE SET vehicle_id = $2, active = true", body.device_id, body.vehicle_id)
#         return {"registered": True, "device_id": body.device_id, "device_name": body.device_name, "vehicle_id": body.vehicle_id, "message": f"ผูก {body.device_id} กับรถ ID {body.vehicle_id} สำเร็จ"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         await conn.close()

# class BatchRegisterRequest(BaseModel):
#     devices: List[RegisterDeviceRequest]

# @router.post("/config_device/register/batch")
# async def register_device_batch(
#     body: BatchRegisterRequest,
#     api_key: str = Security(verify_api_key)
# ):
#     """Odoo ส่ง vehicle_id + device_id หลายคันพร้อมกัน"""
#     conn = await get_db_connection()
#     results = []
#     try:
#         for item in body.devices:
#             await conn.execute("INSERT INTO update_status (vehicle_id, device_id, date_update_latest) VALUES ($1, $2, NOW()) ON CONFLICT (vehicle_id, device_id) DO UPDATE SET date_update_latest = NOW()", item.vehicle_id, item.device_id)
#             await conn.execute("INSERT INTO devices (id, vehicle_id, active) VALUES ($1, $2, true) ON CONFLICT (id) DO UPDATE SET vehicle_id = $2, active = true", item.device_id, item.vehicle_id)
#             results.append({"device_id": item.device_id, "device_name": item.device_name, "vehicle_id": item.vehicle_id, "registered": True})
#         return {"total": len(results), "results": results}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         await conn.close()

# # ============================================================
# # GET /api/v1/devices
# # ดึง device ทั้งหมด พร้อมสถานะว่าผูกกับรถไหนแล้ว
# # ============================================================
# @router.get("/devices")
# async def get_all_devices(
#     api_key: str = Security(verify_api_key)
# ):
#     """
#     GET /api/v1/devices
#     ดึง device ทั้งหมดในระบบ
#     - vehicle_id = null → ยังไม่ได้ผูกกับรถ (available)
#     - vehicle_id = มีค่า → ใช้แล้ว
#     """
#     conn = await get_db_connection()
#     try:
#         rows = await conn.fetch(
#             """
#             SELECT 
#                 d.id AS device_id,
#                 d.vehicle_id,
#                 d.active,
#                 CASE 
#                     WHEN d.vehicle_id IS NULL THEN true
#                     ELSE false
#                 END AS available,
#                 us.date_update_latest
#             FROM devices d
#             LEFT JOIN update_status us 
#                 ON d.id = us.device_id
#             ORDER BY d.id ASC
#             """
#         )
#         return [dict(r) for r in rows]
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         await conn.close()
# โค้ดใหม่
# app/api/routes_config.py
from fastapi import APIRouter, HTTPException, Security, Body
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import List
import asyncpg
from app.config import settings

router = APIRouter(prefix="/api/v1", tags=["Config"])

API_KEY = "ktc-fleet-2026-secret"
api_key_header = APIKeyHeader(name="APIKEY", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="API Key ไม่ถูกต้อง")
    return api_key

async def get_db_connection():
    return await asyncpg.connect(
        user=settings.DB_USER,
        password=settings.DB_PASS,
        database=settings.DB_NAME,
        host=settings.DB_HOST,
        port=settings.DB_PORT
    )

class RegisterDeviceRequest(BaseModel):
    device_id:   str
    device_name: str
    vehicle_id:  int

class BatchRegisterRequest(BaseModel):
    devices: List[RegisterDeviceRequest]


# ============================================================
# helper function สำหรับผูก device กับรถ (ใช้ร่วมกันทั้ง single และ batch)
# ============================================================
async def _register_single(conn, item: RegisterDeviceRequest):
    """
    จัดการความสัมพันธ์แบบ 1-to-1 ระหว่าง รถ (vehicle_id) และ บอร์ด (device_id)
    - รถ 1 คัน มีบอร์ดผูกได้แค่ 1 ตัว
    - บอร์ด 1 ตัว ผูกกับรถได้แค่ 1 คัน
    """
    
    # [กรณี: รถเดิม + บอร์ดใหม่] -> ปลดบอร์ดเก่าตัวอื่นที่เคยผูกกับรถคันนี้ออกก่อน
    # อัปเดตบอร์ดตัวอื่นที่เคยใช้ vehicle_id นี้ ให้กลายเป็นว่าง (NULL)
    await conn.execute("""
        UPDATE devices 
        SET vehicle_id = NULL, active = false 
        WHERE vehicle_id = $1 AND id != $2
    """, item.vehicle_id, item.device_id)
    
    # ลบสถานะเดิมของบอร์ดอื่นที่เคยผูกกับรถคันนี้ออกซะ
    await conn.execute("""
        DELETE FROM update_status 
        WHERE vehicle_id = $1 AND device_id != $2
    """, item.vehicle_id, item.device_id)

    # [กรณี: บอร์ดเดิม + รถใหม่] -> ปลดรถคันเก่าออกจากบอร์ดตัวนี้ก่อน
    # ค้นหาว่าบอร์ดตัวนี้เคยผูกกับรถคันอื่นคันไหนอยู่หรือไม่ (ถ้ามีให้เคลียร์ค่าใน update_status ของคู่นั้นทิ้ง)
    await conn.execute("""
        DELETE FROM update_status 
        WHERE device_id = $1 AND vehicle_id != $2
    """, item.device_id, item.vehicle_id)

    # บันทึกสถานะการผูกคู่ใหม่ลง update_status (หากซ้ำคู่เดิมจะทำการอัปเดตเวลาล่าสุด)
    await conn.execute("""
        INSERT INTO update_status (vehicle_id, device_id, date_update_latest)
        VALUES ($1, $2, NOW())
        ON CONFLICT (vehicle_id, device_id)
        DO UPDATE SET date_update_latest = NOW()
    """, item.vehicle_id, item.device_id)

    # อัปเดตตารางหลัก devices ให้ผูกกับรถคันใหม่และเปิดใช้งาน (active = true)
    await conn.execute("""
        INSERT INTO devices (id, vehicle_id, active)
        VALUES ($1, $2, true)
        ON CONFLICT (id)
        DO UPDATE SET vehicle_id = $2, active = true
    """, item.device_id, item.vehicle_id)


# ============================================================
# GET /api/v1/devices
# ============================================================
@router.get("/devices")
async def get_all_devices(api_key: str = Security(verify_api_key)):
    """ดึง device ทั้งหมด — available=true คือยังไม่ได้ผูกกับรถ"""
    conn = await get_db_connection()
    try:
        rows = await conn.fetch("""
            SELECT 
                d.id AS device_id,
                d.vehicle_id,
                d.active,
                CASE WHEN d.vehicle_id IS NULL THEN true ELSE false END AS available,
                us.date_update_latest
            FROM devices d
            LEFT JOIN update_status us ON d.id = us.device_id
            ORDER BY d.id ASC
        """)
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ============================================================
# GET /api/v1/config_device
# ============================================================
@router.get("/config_device")
async def get_config_device(
    device_id:   str = "",
    device_name: str = "",
    api_key: str = Security(verify_api_key)
):
    """ตรวจสอบว่า device นี้มีในฐานข้อมูลหรือไม่"""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            "SELECT vehicle_id, device_id, date_update_latest FROM update_status WHERE device_id = $1 LIMIT 1",
            device_id
        )
        if row:
            return {"found": True, "device_id": row["device_id"], "device_name": device_name, "vehicle_id": row["vehicle_id"], "date_update_latest": row["date_update_latest"]}
        else:
            return {"found": False, "device_id": "", "device_name": "", "vehicle_id": None, "date_update_latest": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ============================================================
# POST /api/v1/config_device/register (ทีละคัน)
# ============================================================
@router.post("/config_device/register")
async def register_device(
    body: RegisterDeviceRequest,
    api_key: str = Security(verify_api_key)
):
    """ผูก device กับรถ ทีละคัน (ปลอดภัยด้วยระบบ Transaction)"""
    conn = await get_db_connection()
    try:
        # ใช้ transaction ครอบ เพื่อป้องกันกรณีที่คำสั่ง SQL บางคำสั่งทำงานพลาด
        async with conn.transaction():
            await _register_single(conn, body)
            
        return {
            "registered": True,
            "device_id": body.device_id,
            "device_name": body.device_name,
            "vehicle_id": body.vehicle_id,
            "message": f"ผูก บอร์ด {body.device_id} กับรถ ID {body.vehicle_id} สำเร็จ"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ============================================================
# GET /api/v1/config/scoring/current — ดู active scoring config
# ============================================================
@router.get("/config/scoring/current")
async def get_current_scoring_config(api_key: str = Security(verify_api_key)):
    """ดู active scoring config ที่ Backend ใช้อยู่"""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM scoring_config_cache WHERE is_active = TRUE LIMIT 1"
        )
        if not row:
            raise HTTPException(status_code=404, detail="ไม่พบ config")
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ============================================================
# POST /api/v1/config/scoring — Odoo push scoring config ใหม่
# ============================================================
@router.post("/config/scoring")
async def update_scoring_config(
    new_config: dict = Body(...),
    api_key: str = Security(verify_api_key)
):
    """Odoo push scoring config ใหม่ → อัปเดต cache + Event Processor ทันที"""
    conn = await get_db_connection()
    try:
        async with conn.transaction():
            # 1) บันทึกลง scoring_config (history log)
            import json
            config_json = json.dumps(new_config)
            await conn.execute(
                "INSERT INTO scoring_config (config_name, config_data, updated_at) "
                "VALUES ('default', $1, NOW()) "
                "ON CONFLICT (config_name) DO UPDATE SET config_data = $1, updated_at = NOW()",
                config_json
            )

            # 2) อัปเดต scoring_config_cache ที่ GET อ่านจริง (partial update เฉพาะ field ที่ส่งมา)
            allowed_fields = {
                "weight_harsh_brake", "weight_harsh_accel", "weight_harsh_corner",
                "weight_speeding", "weight_idling",
                "threshold_brake_g", "threshold_accel_g", "threshold_corner_g",
                "threshold_speed_kmh", "threshold_idle_min",
                "tier_a_min_score", "tier_b_min_score", "tier_c_min_score",
                "tier_a_bonus_pct", "tier_b_bonus_pct", "tier_c_bonus_pct", "tier_d_bonus_pct",
                "pushed_from_odoo_config_id", "pushed_by"
            }
            updates = {k: v for k, v in new_config.items() if k in allowed_fields}
            if updates:
                set_clause = ", ".join(
                    f"{col} = ${i+1}" for i, col in enumerate(updates.keys())
                )
                values = list(updates.values())
                await conn.execute(
                    f"UPDATE scoring_config_cache SET {set_clause}, pushed_at = NOW() "
                    f"WHERE is_active = TRUE",
                    *values
                )

        updated_fields = list(updates.keys()) if updates else []
        return {
            "status": "success",
            "message": "อัปเดตเกณฑ์คะแนนและข้อยกเว้นในระบบสำเร็จ!",
            "updated_fields": updated_fields
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ============================================================
# POST /api/v1/webhook/odoo-sync — Odoo pull trip logs
# ============================================================
@router.post("/webhook/odoo-sync")
async def odoo_sync_webhook(
    body: dict = Body(...),
    api_key: str = Security(verify_api_key)
):
    """
    Odoo เรียก endpoint นี้เพื่อดึง trip logs ที่ยังไม่ได้ sync
    รับ: vehicle_id (optional), limit (default 50, max 200 ตาม FDD)
    """
    conn = await get_db_connection()
    try:
        vehicle_id = body.get("vehicle_id")
        limit = min(int(body.get("limit", 50)), 200)  # cap ที่ 200 ตาม FDD

        if vehicle_id:
            rows = await conn.fetch("""
                SELECT * FROM trip_logs
                WHERE vehicle_id = $1 AND synced_to_odoo = FALSE
                ORDER BY trip_start DESC LIMIT $2
            """, int(vehicle_id), limit)
        else:
            rows = await conn.fetch("""
                SELECT * FROM trip_logs
                WHERE synced_to_odoo = FALSE
                ORDER BY trip_start DESC LIMIT $1
            """, limit)

        return {"total": len(rows), "trips": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ============================================================
# POST /api/v1/config_device/register/batch (หลายคันพร้อมกัน)
# ============================================================
@router.post("/config_device/register/batch")
async def register_device_batch(
    body: BatchRegisterRequest,
    api_key: str = Security(verify_api_key)
):
    """ผูก device กับรถ หลายคันพร้อมกัน — หากพังแม้แต่คันเดียว ระบบจะย้อนกลับทั้งหมดเพื่อความปลอดภัย"""
    conn = await get_db_connection()
    results = []
    try:
        # ใช้ transaction ครอบคลุมทั้งลูป หากตัวใดตัวหนึ่งพัง ทั้งหมดจะถูกยกเลิก (All-or-Nothing)
        async with conn.transaction():
            for item in body.devices:
                await _register_single(conn, item)
                results.append({
                    "device_id": item.device_id,
                    "device_name": item.device_name,
                    "vehicle_id": item.vehicle_id,
                    "registered": True
                })
        return {"total": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()