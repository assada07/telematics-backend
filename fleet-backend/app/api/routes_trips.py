# app/api/routes_trips.py
from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any
import asyncpg
import json
from app.config import settings

router = APIRouter(prefix="/trips", tags=["Trips & Scoring"])

async def get_db_connection():
    return await asyncpg.connect(
        user=settings.DB_USER,
        password=settings.DB_PASS,
        database=settings.DB_NAME,
        host=settings.DB_HOST,
        port=settings.DB_PORT
    )

# 🎯 1. ช่องทางให้หน้าบ้านดึงสูตรคะแนน/ตัวแปรปัจจุบัน ไปวาดปุ่มกดบนหน้าจอ UI
@router.get("/scoring/config")
async def get_current_scoring_config():
    try:
        conn = await get_db_connection()
        row = await conn.fetchrow(
            "SELECT * FROM scoring_config_cache WHERE is_active = TRUE LIMIT 1"
        )
        await conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="ไม่พบ config")
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 🎯 2. ช่องทางรับข้อมูลเมื่อฝั่งหน้าบ้านกดเปลี่ยนเกณฑ์คะแนน/สวิตช์ข้อยกเว้น แล้วบันทึกส่งมา
@router.post("/scoring/config")
async def update_scoring_config(new_config: Dict[str, Any] = Body(...)):
    """หน้าบ้านส่ง JSON ค่าตัวแปรสูตรคะแนนชุดใหม่มาบันทึกอัปเดตระบบหลังบ้าน"""
    try:
        conn = await get_db_connection()
        config_json = json.dumps(new_config)
        await conn.execute(
            "INSERT INTO scoring_config (config_name, config_data, updated_at) VALUES ('default', $1, NOW()) "
            "ON CONFLICT (config_name) DO UPDATE SET config_data = $1, updated_at = NOW()",
            config_json
        )
        await conn.close()
        return {"status": "success", "message": "อัปเดตเกณฑ์คะแนนและข้อยกเว้นในระบบสำเร็จ!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))