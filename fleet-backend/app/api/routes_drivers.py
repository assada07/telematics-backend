# app/api/routes_drivers.py

"""
Drivers & Incentive API

Endpoints:
  GET /api/v1/drivers/{driver_id}/bonus         — โบนัสสะสม
  GET /api/v1/drivers/{driver_id}/score         — คะแนนเฉลี่ย + trend
  GET /api/v1/drivers/{driver_id}/events        — ประวัติ harsh event
  GET /api/v1/drivers/{driver_id}/fuel-summary  — สรุปการใช้เชื้อเพลิง

Bug 2 Fix:
  /bonus เดิมไม่กรอง driver_id → ดึงทริปของทุกคนมารวมกัน
  แก้แล้ว: WHERE driver_id = $1 ทุก endpoint
"""

from fastapi import APIRouter, HTTPException
import asyncpg
from app.config import settings

router = APIRouter(
    prefix="/api/v1/drivers",
    tags=["Drivers & Incentive Rewards"],
)


async def get_db_connection() -> asyncpg.Connection:
    return await asyncpg.connect(
        user=settings.DB_USER,
        password=settings.DB_PASS,
        database=settings.DB_NAME,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
    )


def _parse_driver_id(driver_id: str) -> int:
    """
    แปลง driver_id string → int
    คืน 0 ถ้าไม่ใช่ตัวเลข เพื่อไม่ให้ query crash
    """
    return int(driver_id) if driver_id.isdigit() else 0


# ================================================================
# GET /api/v1/drivers/{driver_id}/bonus
#
# Bug 2 Fix:
#   เดิม:  WHERE synced_to_odoo = FALSE   ← ไม่กรอง driver_id!
#   แก้:   WHERE driver_id = $1 AND synced_to_odoo = FALSE
#
#   ผลที่ต้องการ: คืนโบนัสของพนักงานคนนั้นเท่านั้น
# ================================================================

@router.get("/{driver_id}/bonus")
async def get_driver_accumulated_bonus(driver_id: str):
    """
    ดึงยอดโบนัสสะสมของพนักงานขับรถ (เฉพาะคนที่ขอเท่านั้น)

    เกณฑ์:
    - ทริปที่มี driver_score ≥ 85 → ได้โบนัส 50 บาท/ทริป
    - นับเฉพาะทริปที่ยังไม่ sync ไป Odoo
    """

    did = _parse_driver_id(driver_id)

    try:
        conn = await get_db_connection()

        # ── FIX: เพิ่ม driver_id = $1 ──────────────────────────
        rows = await conn.fetch(
            """
            SELECT driver_score
            FROM trip_logs
            WHERE driver_id = $1
              AND synced_to_odoo = FALSE
            """,
            did,
        )

        await conn.close()

        qualified = [r for r in rows if r["driver_score"] >= 85.0]

        return {
            "driver_id":                  driver_id,
            "billing_cycle_status":       "Active",
            "total_trips_checked":        len(rows),
            "safe_trips_count":           len(qualified),
            "accumulated_incentive_bonus": len(qualified) * 50.0,
            "currency":                   "THB",
            "bonus_per_safe_trip_thb":    50.0,
            "safe_trip_threshold_score":  85.0,
            "odoo_integration_ready":     True,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# GET /api/v1/drivers/{driver_id}/score
# ================================================================

@router.get("/{driver_id}/score")
async def get_driver_score(driver_id: str):
    """
    ดึงคะแนนเฉลี่ยและ trend รายเดือน 6 เดือนล่าสุดของพนักงาน
    """

    did = _parse_driver_id(driver_id)

    try:
        conn = await get_db_connection()

        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                    AS total_trips,
                ROUND(AVG(driver_score)::numeric, 2)        AS avg_score,
                MAX(driver_score)                           AS max_score,
                MIN(driver_score)                           AS min_score,
                ROUND(SUM(distance_km)::numeric, 2)         AS total_distance_km,
                ROUND(SUM(idle_min)::numeric, 2)            AS total_idle_min,
                SUM(harsh_brake_count)                      AS total_harsh_brake,
                SUM(harsh_accel_count)                      AS total_harsh_accel,
                SUM(harsh_corner_count)                     AS total_harsh_corner,
                SUM(speeding_count)                         AS total_speeding
            FROM trip_logs
            WHERE driver_id = $1
            """,
            did,
        )

        trend = await conn.fetch(
            """
            SELECT
                TO_CHAR(DATE_TRUNC('month', trip_start), 'YYYY-MM')
                                                        AS month,
                COUNT(*)                                AS trips,
                ROUND(AVG(driver_score)::numeric, 2)    AS avg_score,
                ROUND(SUM(distance_km)::numeric, 2)     AS total_km
            FROM trip_logs
            WHERE driver_id = $1
              AND trip_start >= NOW() - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', trip_start)
            ORDER BY month DESC
            """,
            did,
        )

        # ── Incentive tier จาก avg_score ──────────────────────
        avg = float(summary["avg_score"] or 0)
        if avg >= 90:
            tier, bonus_pct = "A", 10.0
        elif avg >= 75:
            tier, bonus_pct = "B", 5.0
        elif avg >= 60:
            tier, bonus_pct = "C", 2.0
        else:
            tier, bonus_pct = "D", 0.0

        await conn.close()

        return {
            "driver_id":    driver_id,
            "summary":      dict(summary) if summary else {},
            "incentive_tier": tier,
            "bonus_pct":    bonus_pct,
            "monthly_trend": [dict(t) for t in trend],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# GET /api/v1/drivers/{driver_id}/events
# ================================================================

@router.get("/{driver_id}/events")
async def get_driver_events(
    driver_id: str,
    limit:     int = 50,
):
    """
    ดึงประวัติ harsh event ของพนักงาน
    (harsh_brake, harsh_acceleration, harsh_cornering, speeding, idling)
    """

    did = _parse_driver_id(driver_id)

    try:
        conn = await get_db_connection()

        # หา device_id ทุกตัวที่พนักงานคนนี้เคยขับ
        trips = await conn.fetch(
            """
            SELECT DISTINCT device_id
            FROM trip_logs
            WHERE driver_id = $1
            """,
            did,
        )

        device_ids = [t["device_id"] for t in trips]

        if not device_ids:
            await conn.close()
            return {
                "driver_id": driver_id,
                "events":    [],
                "total":     0,
            }

        events = await conn.fetch(
            """
            SELECT
                ts, device_id, lat, lon,
                speed, event, event_severity
            FROM telemetry_raw
            WHERE device_id = ANY($1::text[])
              AND event IS NOT NULL
              AND event != ''
            ORDER BY ts DESC
            LIMIT $2
            """,
            device_ids,
            limit,
        )

        await conn.close()

        return {
            "driver_id": driver_id,
            "total":     len(events),
            "events":    [dict(e) for e in events],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# GET /api/v1/drivers/{driver_id}/fuel-summary
# ================================================================

@router.get("/{driver_id}/fuel-summary")
async def get_driver_fuel_summary(driver_id: str):
    """
    สรุปการใช้เชื้อเพลิงและ idling time ของพนักงาน
    """

    did = _parse_driver_id(driver_id)

    try:
        conn = await get_db_connection()

        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                        AS total_trips,
                ROUND(SUM(fuel_used)::numeric,    2)            AS total_fuel_used,
                ROUND(AVG(fuel_used)::numeric,    2)            AS avg_fuel_per_trip,
                ROUND(SUM(distance_km)::numeric,  2)            AS total_distance_km,
                ROUND(SUM(idle_min)::numeric,     2)            AS total_idle_min,
                ROUND(
                    CASE
                        WHEN SUM(distance_km) > 0
                        THEN SUM(fuel_used) / SUM(distance_km) * 100
                        ELSE 0
                    END::numeric, 2
                )                                               AS avg_fuel_per_100km
            FROM trip_logs
            WHERE driver_id = $1
            """,
            did,
        )

        await conn.close()

        result = dict(summary) if summary else {}
        result["driver_id"] = driver_id
        result["unit"]       = "ลิตร"

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))