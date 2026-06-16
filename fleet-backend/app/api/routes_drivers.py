# # app/api/routes_drivers.py
# from fastapi import APIRouter, HTTPException
# import asyncpg
# from app.config import settings

# router = APIRouter(prefix="/drivers", tags=["Drivers & Incentive Rewards"])

# @router.get("/{driver_id}/bonus")
# async def get_driver_accumulated_bonus(driver_id: str):
#     """
#     หน้าบ้าน (Frontend) ดึง endpoint นี้ไปพล็อตกราฟรายรับและเบี้ยขยันของพนักงานขับรถ
#     และระบบ Odoo 17 จะใช้ดึงไปคำนวณยอดสลิปเงินเดือน (Payroll) อัตโนมัติ
#     """
#     try:
#         conn = await asyncpg.connect(
#             user=settings.DB_USER, password=settings.DB_PASS,
#             database=settings.DB_NAME, host=settings.DB_HOST, port=settings.DB_PORT
#         )
#         # ค้นหาประวัติทริปทั้งหมดของคนขับที่ปลอดภัย (Safety Score >= 85 แต้ม) และยังไม่ได้นำไปตัดยอดบัญชี
#         rows = await conn.fetch(
#             "SELECT driver_score FROM trip_logs WHERE synced_to_odoo = FALSE"
# )
#         await conn.close()

#         # เงื่อนไขโบนัสจูงใจ: ทริปที่มีพฤติกรรมขับขี่ปลอดภัยสูง ได้รับเงินรางวัลพิเศษทริปละ 50 บาท
#         qualified_safe_trips = [r for r in rows if r['driver_score'] >= 85.0]
#         total_bonus_thb = len(qualified_safe_trips) * 50.0

#         return {
#             "driver_id": driver_id,
#             "billing_cycle_status": "Active",
#             "safe_trips_count": len(qualified_safe_trips),
#             "accumulated_incentive_bonus": total_bonus_thb,
#             "currency": "THB",
#             "odoo_integration_ready": True
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# app/api/routes_drivers.py (เพิ่ม score, events, fuel-summary)
from fastapi import APIRouter, HTTPException
import asyncpg
from app.config import settings

router = APIRouter(prefix="/drivers", tags=["Drivers & Incentive Rewards"])


async def get_db_connection():
    return await asyncpg.connect(
        user=settings.DB_USER,
        password=settings.DB_PASS,
        database=settings.DB_NAME,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
    )


# ============================================================
# GET /drivers/{driver_id}/bonus
# ============================================================
@router.get("/{driver_id}/bonus")
async def get_driver_accumulated_bonus(driver_id: str):
    """ดึงยอดโบนัสสะสมของพนักงานขับรถ"""
    try:
        conn = await get_db_connection()
        rows = await conn.fetch(
            "SELECT driver_score FROM trip_logs WHERE synced_to_odoo = FALSE"
        )
        await conn.close()
        qualified = [r for r in rows if r["driver_score"] >= 85.0]
        return {
            "driver_id": driver_id,
            "billing_cycle_status": "Active",
            "safe_trips_count": len(qualified),
            "accumulated_incentive_bonus": len(qualified) * 50.0,
            "currency": "THB",
            "odoo_integration_ready": True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# GET /drivers/{driver_id}/score — คะแนนเฉลี่ย + trend
# ============================================================
@router.get("/{driver_id}/score")
async def get_driver_score(driver_id: str):
    """ดึงคะแนนเฉลี่ยและ trend รายเดือนของพนักงาน"""
    try:
        conn = await get_db_connection()

        # คะแนนเฉลี่ยทั้งหมด
        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_trips,
                ROUND(AVG(driver_score)::numeric, 2) AS avg_score,
                MAX(driver_score) AS max_score,
                MIN(driver_score) AS min_score
            FROM trip_logs
            WHERE driver_id = $1
        """,
            int(driver_id) if driver_id.isdigit() else 0,
        )

        # trend รายเดือน 6 เดือนล่าสุด
        trend = await conn.fetch(
            """
            SELECT
                TO_CHAR(DATE_TRUNC('month', trip_start), 'YYYY-MM') AS month,
                COUNT(*) AS trips,
                ROUND(AVG(driver_score)::numeric, 2) AS avg_score
            FROM trip_logs
            WHERE driver_id = $1
              AND trip_start >= NOW() - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', trip_start)
            ORDER BY month DESC
        """,
            int(driver_id) if driver_id.isdigit() else 0,
        )

        await conn.close()
        return {
            "driver_id": driver_id,
            "summary": dict(summary) if summary else {},
            "monthly_trend": [dict(t) for t in trend],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# GET /drivers/{driver_id}/events — ประวัติ harsh event
# ============================================================
@router.get("/{driver_id}/events")
async def get_driver_events(driver_id: str, limit: int = 50):
    """ดึงประวัติ harsh event ของพนักงาน (harsh_brake, harsh_acceleration, harsh_cornering)"""
    try:
        conn = await get_db_connection()

        # ดึง device_id จาก driver_id ผ่าน trip_logs
        trips = await conn.fetch(
            """
            SELECT DISTINCT device_id FROM trip_logs
            WHERE driver_id = $1
        """,
            int(driver_id) if driver_id.isdigit() else 0,
        )

        device_ids = [t["device_id"] for t in trips]
        if not device_ids:
            await conn.close()
            return {"driver_id": driver_id, "events": [], "total": 0}

        events = await conn.fetch(
            """
            SELECT ts, device_id, lat, lon, speed, event, event_severity
            FROM telemetry_raw
            WHERE device_id = ANY($1::text[])
              AND event IS NOT NULL AND event != ''
            ORDER BY ts DESC
            LIMIT $2
        """,
            device_ids,
            limit,
        )

        await conn.close()
        return {
            "driver_id": driver_id,
            "total": len(events),
            "events": [dict(e) for e in events],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# GET /drivers/{driver_id}/fuel-summary — สรุปเชื้อเพลิง
# ============================================================
@router.get("/{driver_id}/fuel-summary")
async def get_driver_fuel_summary(driver_id: str):
    """สรุปการใช้เชื้อเพลิงของพนักงาน"""
    try:
        conn = await get_db_connection()

        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_trips,
                ROUND(SUM(fuel_used)::numeric, 2) AS total_fuel_used,
                ROUND(AVG(fuel_used)::numeric, 2) AS avg_fuel_per_trip,
                ROUND(SUM(distance_km)::numeric, 2) AS total_distance_km,
                ROUND(
                    CASE WHEN SUM(distance_km) > 0
                    THEN SUM(fuel_used) / SUM(distance_km) * 100
                    ELSE 0 END::numeric, 2
                ) AS avg_fuel_per_100km
            FROM trip_logs
            WHERE driver_id = $1
        """,
            int(driver_id) if driver_id.isdigit() else 0,
        )

        await conn.close()
        result = dict(summary) if summary else {}
        result["driver_id"] = driver_id
        result["unit"] = "ลิตร"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
