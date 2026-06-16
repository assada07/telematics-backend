# app/services/score_calculator.py

import datetime
from typing import List, Dict, Any


def calculate_advanced_trip_score(
    telemetry_data: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    คำนวณคะแนนความปลอดภัยรายเที่ยว

    FDD v1.4
    - Pure function
    - Event-based scoring
    - Event Count (FSM)
    - No DB
    - No API
    - No Odoo
    """

    if not telemetry_data:
        return {
            "safety_score": config.get("score_base", 100.0),
            "metrics": {}
        }

    # ==========================================================
    # Config
    # ==========================================================
    score_base = float(
        config.get("score_base", 100.0)
    )

    weight_speeding = float(
        config.get("weight_speeding", 5.0)
    )

    weight_harsh_brake = float(
        config.get("weight_harsh_brake", 3.0)
    )

    weight_harsh_accel = float(
        config.get("weight_harsh_accel", 3.0)
    )

    weight_harsh_corner = float(
        config.get("weight_harsh_corner", 2.0)
    )

    weight_idling = float(
        config.get("weight_idling", 1.0)
    )

    idle_min_threshold = float(
        config.get("idle_min_threshold", 5.0)
    )

    max_deduct_per_trip = float(
        config.get("max_deduct_per_trip", 100.0)
    )

    night_multiplier = float(
        config.get(
            "night_danger_zone_multiplier",
            1.5
        )
    )

    # ==========================================================
    # Metrics
    # ==========================================================
    speeding_count = 0
    harsh_brake_count = 0
    harsh_accel_count = 0
    harsh_corner_count = 0

    max_speed = 0.0

    # ==========================================================
    # Penalties
    # ==========================================================
    speeding_penalty = 0.0
    brake_penalty = 0.0
    accel_penalty = 0.0
    corner_penalty = 0.0
    idle_penalty = 0.0

    # ==========================================================
    # FSM State
    # ==========================================================
    in_speeding_event = False
    in_brake_event = False
    in_accel_event = False
    in_corner_event = False

    # ==========================================================
    # Idle Duration
    # ==========================================================
    idle_start_ts = None
    total_idle_seconds = 0.0

    # ==========================================================
    # Main Loop
    # ==========================================================
    for point in telemetry_data:

        speed = float(
            point.get("speed") or 0.0
        )

        lat = float(
            point.get("lat") or 0.0
        )

        ts = point.get("ts")

        event = point.get("event")

        # ------------------------------------------------------
        # max speed
        # ------------------------------------------------------
        if speed > max_speed:
            max_speed = speed

        # ------------------------------------------------------
        # multiplier
        # ------------------------------------------------------
        multiplier = 1.0

        if (
            ts
            and isinstance(
                ts,
                datetime.datetime
            )
        ):
            if 0 <= ts.hour < 4:
                multiplier = night_multiplier

        # ======================================================
        # Speeding Event
        # ======================================================
        is_speeding = (
            event == "speeding"
        )

        if (
            is_speeding
            and not in_speeding_event
        ):
            speeding_count += 1

            speeding_penalty += (
                weight_speeding
                * multiplier
            )

        in_speeding_event = is_speeding

        # ======================================================
        # Harsh Brake Event
        # ======================================================
        is_brake = (
            event == "harsh_brake"
        )

        if (
            is_brake
            and not in_brake_event
        ):

            is_exempt_low_speed = (
                (
                    config.get(
                        "enable_construction_zone_exemption",
                        True
                    )
                    or
                    config.get(
                        "enable_accident_delay_exemption",
                        True
                    )
                )
                and speed < 20.0
            )

            is_mountain = (
                config.get(
                    "enable_mountain_road_exemption",
                    True
                )
                and 18.5 < lat < 19.5
            )

            if is_exempt_low_speed:
                pass

            elif is_mountain:

                harsh_brake_count += 1

                brake_penalty += (
                    weight_harsh_brake
                    * 0.5
                    * multiplier
                )

            else:

                harsh_brake_count += 1

                brake_penalty += (
                    weight_harsh_brake
                    * multiplier
                )

        in_brake_event = is_brake

        # ======================================================
        # Harsh Acceleration Event
        # ======================================================
        is_accel = (
            event == "harsh_acceleration"
        )

        if (
            is_accel
            and not in_accel_event
        ):

            harsh_accel_count += 1

            accel_penalty += (
                weight_harsh_accel
                * multiplier
            )

        in_accel_event = is_accel

        # ======================================================
        # Harsh Corner Event
        # ======================================================
        is_corner = (
            event == "harsh_cornering"
        )

        if (
            is_corner
            and not in_corner_event
        ):

            is_mountain = (
                config.get(
                    "enable_mountain_road_exemption",
                    True
                )
                and 18.5 < lat < 19.5
            )

            if not is_mountain:

                harsh_corner_count += 1

                corner_penalty += (
                    weight_harsh_corner
                    * multiplier
                )

        in_corner_event = is_corner

        # ======================================================
        # Engine Idling
        # ======================================================
        ignition = (
            point.get("ignition")
            is True
        )

        is_idle = (
            ignition
            and speed == 0.0
        )

        if (
            is_idle
            and idle_start_ts is None
        ):
            idle_start_ts = ts

        elif (
            not is_idle
            and idle_start_ts is not None
        ):

            if (
                isinstance(
                    ts,
                    datetime.datetime
                )
                and isinstance(
                    idle_start_ts,
                    datetime.datetime
                )
            ):

                duration = (
                    ts - idle_start_ts
                ).total_seconds()

                if duration > 0:
                    total_idle_seconds += duration

            idle_start_ts = None

    # ==========================================================
    # close last idle segment
    # ==========================================================
    if (
        idle_start_ts is not None
    ):

        last_ts = telemetry_data[-1].get("ts")

        if (
            isinstance(
                last_ts,
                datetime.datetime
            )
        ):

            duration = (
                last_ts - idle_start_ts
            ).total_seconds()

            if duration > 0:
                total_idle_seconds += duration

    engine_idle_minutes = (
        total_idle_seconds / 60.0
    )

    # ==========================================================
    # idling penalty
    # ==========================================================
    all_exempt = (
        config.get(
            "enable_traffic_jam_exemption",
            True
        )
        or
        config.get(
            "enable_warehouse_idling_exemption",
            True
        )
        or
        config.get(
            "enable_night_rest_exemption",
            True
        )
    )

    if (
        engine_idle_minutes
        > idle_min_threshold
        and not all_exempt
    ):

        idle_penalty = (
            engine_idle_minutes
            - idle_min_threshold
        ) * weight_idling

    # ==========================================================
    # Total deduction
    # ==========================================================
    total_deduct = (
        speeding_penalty
        + brake_penalty
        + accel_penalty
        + corner_penalty
        + idle_penalty
    )

    total_deduct = min(
        total_deduct,
        max_deduct_per_trip
    )

    final_score = (
        score_base
        - total_deduct
    )

    final_score = max(
        0.0,
        min(
            score_base,
            final_score
        )
    )

    # ==========================================================
    # Metrics
    # ==========================================================
    metrics = {
        "max_speed": round(
            max_speed,
            2
        ),
        "speeding_count": speeding_count,
        "harsh_brake_count": harsh_brake_count,
        "harsh_accel_count": harsh_accel_count,
        "harsh_corner_count": harsh_corner_count,
        "engine_idle_minutes": round(
            engine_idle_minutes,
            2
        ),
    }

    return {
        "safety_score": round(
            final_score,
            2
        ),
        "metrics": metrics
    }