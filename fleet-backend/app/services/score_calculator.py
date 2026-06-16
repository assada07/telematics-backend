# app/services/score_calculator.py
import datetime
from typing import List, Dict, Any


def calculate_advanced_trip_score(
    telemetry_data: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    คำนวณคะแนนความปลอดภัยรายเที่ยว
    อ่านเกณฑ์จาก config (มาจาก scoring_config_cache) ตาม FDD v1.4
    """
    if not telemetry_data:
        return {"safety_score": config.get("score_base", 100.0), "metrics": {}}

    score = config.get("score_base", 100.0)
    overspeed_limit = config.get("speeding_kmh_over", 90.0)
    overspeed_deduct = config.get("speeding_deduct", 5.0)
    brake_deduct = config.get("harsh_brake_deduct", 3.0)
    accel_deduct = config.get("harsh_accel_deduct", 3.0)
    corner_deduct = config.get("harsh_corner_deduct", 2.0)
    idle_deduct_pm = config.get("idling_deduct", 1.0)
    max_idle_allowed = config.get("idle_min_threshold", 5.0)
    max_deduct = config.get("max_deduct_per_trip", 100.0)
    night_multiplier = config.get("night_danger_zone_multiplier", 1.5)

    overspeed_count = 0
    harsh_brake_count = 0
    harsh_accel_count = 0
    harsh_corner_count = 0
    max_speed = 0.0

    for point in telemetry_data:
        speed = float(point.get("speed") or 0.0)
        ts = point.get("ts")
        lat = float(point.get("lat") or 0.0)

        if speed > max_speed:
            max_speed = speed

        # ─── Multiplier (Circadian Danger Zone 00:00–03:59) ─────────────
        multiplier = 1.0
        if ts and isinstance(ts, datetime.datetime):
            if 0 <= ts.hour < 4:
                multiplier = night_multiplier

        # ─── 1. ความเร็วเกิน ────────────────────────────────────────────
        if speed > overspeed_limit:
            overspeed_count += 1
            score -= overspeed_deduct * multiplier

        # ─── 2. Harsh Brake ─────────────────────────────────────────────
        # BUG FIX: ตรวจจากชื่อ field ที่ query สร้าง (harsh_braking)
        # ซึ่งมาจาก event = 'harsh_brake' ใน telemetry_raw
        if point.get("harsh_braking"):
            is_exempt_low_speed = (
                config.get("enable_construction_zone_exemption", True)
                or config.get("enable_accident_delay_exemption", True)
            ) and speed < 20.0

            is_mountain = (
                config.get("enable_mountain_road_exemption",
                           True) and 18.5 < lat < 19.5
            )

            if is_exempt_low_speed:
                pass  # ยกเว้น (รถติด/เขตก่อสร้าง)
            elif is_mountain:
                score -= brake_deduct * 0.5  # อนุโลมกึ่งหนึ่ง
                harsh_brake_count += 1
            else:
                score -= brake_deduct * multiplier
                harsh_brake_count += 1

        # ─── 3. Harsh Acceleration ──────────────────────────────────────
        if point.get("harsh_acceleration"):
            harsh_accel_count += 1
            score -= accel_deduct * multiplier

        # ─── 4. Harsh Cornering ─────────────────────────────────────────
        if point.get("harsh_cornering"):
            if config.get("enable_mountain_road_exemption", True) and 18.5 < lat < 19.5:
                pass  # ทางโค้งเขา ยกเว้น
            else:
                harsh_corner_count += 1
                score -= corner_deduct * multiplier

    # ─── 5. Idling ──────────────────────────────────────────────────────
    idle_points = [
        p
        for p in telemetry_data
        if float(p.get("speed") or 0.0) == 0.0 and p.get("ignition") is True
    ]
    # ส่งข้อมูลทุก 5 วินาที → 12 จุด/นาที
    total_idle_min = (len(idle_points) * 5) / 60.0

    all_exempt = (
        config.get("enable_traffic_jam_exemption", True)
        or config.get("enable_warehouse_idling_exemption", True)
        or config.get("enable_night_rest_exemption", True)
    )
    if total_idle_min > max_idle_allowed and not all_exempt:
        score -= (total_idle_min - max_idle_allowed) * idle_deduct_pm

    # ─── 6. เพดานหัก + ป้องกัน negative ───────────────────────────────
    base = config.get("score_base", 100.0)
    total_deducted = base - score
    if total_deducted > max_deduct:
        score = base - max_deduct

    final_score = max(0.0, min(base, score))

    return {
        "safety_score": round(final_score, 2),
        "metrics": {
            "max_speed": round(max_speed, 2),
            "speeding_count": overspeed_count,
            "harsh_brake_count": harsh_brake_count,
            "harsh_accel_count": harsh_accel_count,
            "harsh_corner_count": harsh_corner_count,
            "engine_idle_minutes": round(total_idle_min, 2),
        },
    }
