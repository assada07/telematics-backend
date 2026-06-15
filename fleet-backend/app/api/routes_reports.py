# app/api/routes_reports.py (รายงาน 4 ตัว)
from fastapi import APIRouter, HTTPException
import asyncpg
from app.config import settings

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])

async def get_db_connection():
    return await asyncpg.connect(
        user=settings.DB_USER, password=settings.DB_PASS,
        database=settings.DB_NAME, host=settings.DB_HOST, port=settings.DB_PORT
    )

# ============================================================
# GET /api/v1/reports/driver-score — คะแนนรายเดือน
# ============================================================
@router.get("/driver-score")
async def report_driver_score(months: int = 3):
    """รายงานคะแนนพนักงานย้อนหลัง N เดือน"""
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT
                driver_id,
                TO_CHAR(DATE_TRUNC('month', trip_start), 'YYYY-MM') AS month,
                COUNT(*) AS total_trips,
                ROUND(AVG(driver_score)::numeric, 2) AS avg_score,
                SUM(CASE WHEN driver_score >= 85 THEN 1 ELSE 0 END) AS safe_trips,
                SUM(harsh_brake_count) AS total_harsh_brake,
                SUM(speeding_count) AS total_speeding
            FROM trip_logs
            WHERE trip_start >= NOW() - ($1 || ' months')::interval
            GROUP BY driver_id, DATE_TRUNC('month', trip_start)
            ORDER BY month DESC, driver_id ASC
        """, str(months))
        await conn.close()
        return {"months": months, "total_records": len(rows), "data": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# GET /api/v1/reports/fleet-summary — ภาพรวม fleet รายวัน
# ============================================================
@router.get("/fleet-summary")
async def report_fleet_summary(days: int = 7):
    """ภาพรวม fleet รายวัน ย้อนหลัง N วัน"""
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT
                DATE(trip_start) AS date,
                COUNT(*) AS total_trips,
                COUNT(DISTINCT vehicle_id) AS active_vehicles,
                ROUND(AVG(driver_score)::numeric, 2) AS avg_score,
                ROUND(SUM(distance_km)::numeric, 2) AS total_distance_km,
                SUM(harsh_brake_count + harsh_accel_count + harsh_corner_count) AS total_harsh_events,
                SUM(speeding_count) AS total_speeding
            FROM trip_logs
            WHERE trip_start >= NOW() - ($1 || ' days')::interval
            GROUP BY DATE(trip_start)
            ORDER BY date DESC
        """, str(days))
        await conn.close()
        return {"days": days, "total_days": len(rows), "data": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# GET /api/v1/reports/fuel-efficiency — Fuel report
# ============================================================
@router.get("/fuel-efficiency")
async def report_fuel_efficiency(days: int = 30):
    """รายงานประสิทธิภาพเชื้อเพลิงรายรถ"""
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT
                vehicle_id,
                COUNT(*) AS total_trips,
                ROUND(SUM(fuel_used)::numeric, 2) AS total_fuel_used,
                ROUND(SUM(distance_km)::numeric, 2) AS total_distance_km,
                ROUND(
                    CASE WHEN SUM(distance_km) > 0
                    THEN SUM(fuel_used) / SUM(distance_km) * 100
                    ELSE 0 END::numeric, 2
                ) AS fuel_per_100km,
                ROUND(AVG(driver_score)::numeric, 2) AS avg_driver_score
            FROM trip_logs
            WHERE trip_start >= NOW() - ($1 || ' days')::interval
              AND vehicle_id > 0
            GROUP BY vehicle_id
            ORDER BY fuel_per_100km DESC
        """, str(days))
        await conn.close()
        return {"days": days, "unit": "ลิตร", "total_vehicles": len(rows), "data": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# GET /api/v1/reports/maintenance-forecast — คาดการณ์ซ่อมบำรุง
# ============================================================
@router.get("/maintenance-forecast")
async def report_maintenance_forecast():
    """คาดการณ์รถที่ควรเข้าซ่อมบำรุงจากพฤติกรรมการขับ"""
    try:
        conn = await get_db_connection()
        rows = await conn.fetch("""
            SELECT
                vehicle_id,
                COUNT(*) AS total_trips,
                ROUND(SUM(distance_km)::numeric, 2) AS total_distance_km,
                SUM(harsh_brake_count) AS total_harsh_brake,
                SUM(harsh_accel_count) AS total_harsh_accel,
                SUM(harsh_corner_count) AS total_harsh_corner,
                ROUND(AVG(driver_score)::numeric, 2) AS avg_score,
                MAX(trip_end) AS last_trip,
                CASE
                    WHEN SUM(distance_km) > 5000 THEN 'สูง'
                    WHEN SUM(distance_km) > 2000 THEN 'กลาง'
                    ELSE 'ต่ำ'
                END AS maintenance_priority,
                CASE
                    WHEN SUM(distance_km) > 5000
                      OR SUM(harsh_brake_count) > 20 THEN true
                    ELSE false
                END AS needs_maintenance
            FROM trip_logs
            WHERE vehicle_id > 0
              AND trip_start >= NOW() - INTERVAL '30 days'
            GROUP BY vehicle_id
            ORDER BY needs_maintenance DESC, total_distance_km DESC
        """)
        await conn.close()
        return {
            "total_vehicles": len(rows),
            "needs_maintenance": sum(1 for r in rows if r["needs_maintenance"]),
            "data": [dict(r) for r in rows]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))