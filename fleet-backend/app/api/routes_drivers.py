# app/api/routes_drivers.py
from fastapi import APIRouter, HTTPException
import asyncpg
from app.config import settings

router = APIRouter(prefix="/drivers", tags=["Drivers & Incentive Rewards"])

@router.get("/{driver_id}/bonus")
async def get_driver_accumulated_bonus(driver_id: str):
    """
    หน้าบ้าน (Frontend) ดึง endpoint นี้ไปพล็อตกราฟรายรับและเบี้ยขยันของพนักงานขับรถ 
    และระบบ Odoo 17 จะใช้ดึงไปคำนวณยอดสลิปเงินเดือน (Payroll) อัตโนมัติ
    """
    try:
        conn = await asyncpg.connect(
            user=settings.DB_USER, password=settings.DB_PASS,
            database=settings.DB_NAME, host=settings.DB_HOST, port=settings.DB_PORT
        )
        # ค้นหาประวัติทริปทั้งหมดของคนขับที่ปลอดภัย (Safety Score >= 85 แต้ม) และยังไม่ได้นำไปตัดยอดบัญชี
        rows = await conn.fetch(
            "SELECT driver_score FROM trip_logs WHERE synced_to_odoo = FALSE"
)
        await conn.close()
        
        # เงื่อนไขโบนัสจูงใจ: ทริปที่มีพฤติกรรมขับขี่ปลอดภัยสูง ได้รับเงินรางวัลพิเศษทริปละ 50 บาท
        qualified_safe_trips = [r for r in rows if r['driver_score'] >= 85.0]
        total_bonus_thb = len(qualified_safe_trips) * 50.0
        
        return {
            "driver_id": driver_id,
            "billing_cycle_status": "Active",
            "safe_trips_count": len(qualified_safe_trips),
            "accumulated_incentive_bonus": total_bonus_thb,
            "currency": "THB",
            "odoo_integration_ready": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))