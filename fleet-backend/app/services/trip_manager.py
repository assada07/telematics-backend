# app/services/trip_manager.py
import datetime
import logging
import asyncpg
from app.services.score_calculator import calculate_advanced_trip_score

logger = logging.getLogger("TripManager")


async def get_active_scoring_config(connection: asyncpg.Connection) -> dict:
    """ดึงเกณฑ์คำนวณล่าสุดจากตาราง scoring_config_cache"""
    query = "SELECT * FROM scoring_config_cache WHERE is_active = TRUE LIMIT 1;"
    row = await connection.fetchrow(query)
    if row:
        raw = dict(row)
        return {
            "score_base":                         100.0,
            "speeding_kmh_over":                  raw.get("threshold_speed_kmh",  90.0),
            "speeding_deduct":                    raw.get("weight_speeding",       15.0),
            "harsh_brake_deduct":                 raw.get("weight_harsh_brake",    30.0),
            "harsh_accel_deduct":                 raw.get("weight_harsh_accel",    25.0),
            "harsh_corner_deduct":                raw.get("weight_harsh_corner",   20.0),
            "idling_deduct":                      raw.get("weight_idling",         10.0),
            "idle_min_threshold":                 raw.get("threshold_idle_min",     5.0),
            "max_deduct_per_trip":                100.0,
            "night_danger_zone_multiplier":       1.5,
            "enable_construction_zone_exemption": True,
            "enable_accident_delay_exemption":    True,
            "enable_mountain_road_exemption":     True,
            "enable_traffic_jam_exemption":       True,
            "enable_warehouse_idling_exemption":  True,
            "enable_night_rest_exemption":        True,
        }
    return {
        "score_base": 100.0, "speeding_kmh_over": 90.0, "speeding_deduct": 5.0,
        "harsh_brake_deduct": 3.0, "harsh_accel_deduct": 3.0, "harsh_corner_deduct": 2.0,
        "idling_deduct": 1.0, "idle_min_threshold": 5.0, "max_deduct_per_trip": 100.0,
        "night_danger_zone_multiplier": 1.5,
        "enable_construction_zone_exemption": True,
        "enable_accident_delay_exemption":    True,
        "enable_mountain_road_exemption":     True,
        "enable_traffic_jam_exemption":       True,
        "enable_warehouse_idling_exemption":  True,
        "enable_night_rest_exemption":        True,
    }


async def get_vehicle_id_from_update_status(
    connection: asyncpg.Connection,
    device_id: str
) -> int:
    """
    ดึง vehicle_id จากตาราง update_status โดยใช้ device_id
    แทนการ hardcode vehicle_id = 1 แบบเดิม
    """
    row = await connection.fetchrow(
        "SELECT vehicle_id FROM update_status WHERE device_id = $1 LIMIT 1",
        device_id
    )
    if row and row["vehicle_id"]:
        return row["vehicle_id"]
    
    # fallback: ดึงจาก devices table ถ้า update_status ยังไม่มี
    row2 = await connection.fetchrow(
        "SELECT vehicle_id FROM devices WHERE id = $1 LIMIT 1",
        device_id
    )
    if row2 and row2["vehicle_id"]:
        return row2["vehicle_id"]

    logger.warning(f"⚠️ ไม่พบ vehicle_id สำหรับ device_id={device_id} ใช้ค่า 0 แทน")
    return 0  # 0 = ยังไม่ได้ผูกกับรถ


async def process_and_save_trip_summary(
    pool: asyncpg.Pool,
    device_id: str,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
):
    """กวาดข้อมูลดิบของทริป → คำนวณคะแนน → บันทึกลง trip_logs"""
    try:
        async with pool.acquire() as connection:

            # ─────────────────────────────────────────────
            # 1. ดึง vehicle_id จาก update_status (แทน hardcode)
            # ─────────────────────────────────────────────
            vehicle_id = await get_vehicle_id_from_update_status(connection, device_id)
            logger.info(f"[TripManager] {device_id} → vehicle_id={vehicle_id}")

            # ─────────────────────────────────────────────
            # 2. ดึงข้อมูล telemetry ของทริปนี้
            # ─────────────────────────────────────────────
            raw_data_query = """
                SELECT
                    ts, speed, lat, lon, event, ignition,
                    (event = 'harsh_brake')        AS harsh_braking,
                    (event = 'harsh_acceleration') AS harsh_acceleration,
                    (event = 'harsh_cornering')    AS harsh_cornering
                FROM telemetry_raw
                WHERE device_id = $1
                  AND ts BETWEEN $2 AND $3
                ORDER BY ts ASC;
            """
            rows = await connection.fetch(raw_data_query, device_id, start_time, end_time)
            telemetry_points = [dict(r) for r in rows]

            logger.info(
                f"[TripManager] {device_id}: ดึงข้อมูล {len(telemetry_points)} จุด "
                f"ระหว่าง {start_time} → {end_time}"
            )

            # ─────────────────────────────────────────────
            # 3. ดึง Config + คำนวณคะแนน
            # ─────────────────────────────────────────────
            config = await get_active_scoring_config(connection)
            result = calculate_advanced_trip_score(telemetry_points, config)
            metrics = result["metrics"]

            # ─────────────────────────────────────────────
            # 4. คำนวณค่าสรุปทริป
            # ─────────────────────────────────────────────
            duration_min = (end_time - start_time).total_seconds() / 60.0
            speeds = [p["speed"] for p in telemetry_points if p.get("speed") is not None]
            avg_speed = (sum(speeds) / len(speeds)) if speeds else 0.0

            # ─────────────────────────────────────────────
            # 5. INSERT ลง trip_logs (vehicle_id มาจาก update_status)
            # ─────────────────────────────────────────────
            insert_query = """
                INSERT INTO trip_logs (
                    device_id, vehicle_id, driver_id,
                    trip_start, trip_end,
                    distance_km, duration_min, idle_min,
                    max_speed, avg_speed,
                    harsh_brake_count, harsh_accel_count, harsh_corner_count,
                    speeding_count, driver_score,
                    fuel_used, gps_track, synced_to_odoo, created_at
                ) VALUES (
                    $1,  $2,  $3,
                    $4,  $5,
                    $6,  $7,  $8,
                    $9,  $10,
                    $11, $12, $13,
                    $14, $15,
                    $16, $17::jsonb, $18, NOW()
                );
            """
            await connection.execute(
                insert_query,
                device_id,
                vehicle_id,     # ← ดึงจาก update_status แทน hardcode
                0,              # driver_id (placeholder รอ Odoo ผูกโยง)
                start_time,
                end_time,
                0.0,
                round(duration_min, 2),
                round(metrics.get("engine_idle_minutes", 0.0), 2),
                round(metrics.get("max_speed", 0.0), 2),
                round(avg_speed, 2),
                int(metrics.get("harsh_brake_count",  0)),
                int(metrics.get("harsh_accel_count",  0)),
                int(metrics.get("harsh_corner_count", 0)),
                int(metrics.get("speeding_count",     0)),
                result["safety_score"],
                0.0,
                "[]",
                False,
            )

            # ─────────────────────────────────────────────
            # 6. อัปเดต date_update_latest ใน update_status
            # ─────────────────────────────────────────────
            await connection.execute(
                """
                UPDATE update_status
                SET date_update_latest = NOW()
                WHERE device_id = $1
                """,
                device_id
            )

            logger.info(
                f"✅ [Trip Saved] {device_id} | vehicle_id={vehicle_id} | "
                f"Score: {result['safety_score']} | "
                f"Harsh Brakes: {metrics.get('harsh_brake_count', 0)} | "
                f"Speeding: {metrics.get('speeding_count', 0)}"
            )

    except Exception as e:
        logger.error(f"❌ [TripManager Error] {device_id}: {e}", exc_info=True)