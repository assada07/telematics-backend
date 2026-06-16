# regionโค้ดอันเก่าที่แก้ขั้นตอนที่3
# app/services/event_processor.py

# def filter_imu_noise_event(ax: float, ay: float, az: float) -> dict:
#     """
#     วิเคราะห์และกรองสัญญาณรบกวน (Noise Filter) จากข้อมูล G-Force 
#     ป้องกันความผิดพลาดจากสภาพถนนขรุขระ ก่อนนำไปคิดคะแนนความปลอดภัย
#     """
#     # เกณฑ์มาตรฐานสากลความปลอดภัยขนส่ง (G-Force Thresholds)
#     HARSH_BRAKE_THRESHOLD = -0.4  # แรงเบรกแนวดิ่งเชิงลบ
#     HARSH_ACCEL_THRESHOLD = 0.3   # แรงเร่งเครื่องยนต์กระชากไปข้างหน้า
#     HARSH_CORNER_THRESHOLD = 0.5  # แรงเหวี่ยงสลัดซ้ายขวาขณะเข้าโค้ง
    
#     return {
#         "is_harsh_braking": ay < HARSH_BRAKE_THRESHOLD,
#         "is_harsh_acceleration": ay > HARSH_ACCEL_THRESHOLD,
#         "is_harsh_cornering": abs(ax) > HARSH_CORNER_THRESHOLD
#     }
# endregion

# app/services/event_processor.py
from typing import Dict


def filter_imu_noise_event(
    ax: float,
    ay: float,
    az: float
) -> Dict[str, bool]:
    """
    Backward compatibility
    """

    HARSH_BRAKE_THRESHOLD = -0.4
    HARSH_ACCEL_THRESHOLD = 0.3
    HARSH_CORNER_THRESHOLD = 0.5

    ax = ax or 0.0
    ay = ay or 0.0

    return {
        "is_harsh_braking": ay < HARSH_BRAKE_THRESHOLD,
        "is_harsh_acceleration": ay > HARSH_ACCEL_THRESHOLD,
        "is_harsh_cornering": abs(ax) > HARSH_CORNER_THRESHOLD
    }


def _safe_float(value) -> float:
    """
    ป้องกัน None หรือค่าผิดรูปแบบ
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _calculate_severity(
        value: float,
        threshold: float
) -> float:
    """
    normalize severity ให้อยู่ช่วง 0-1
    """

    if threshold <= 0:
        return 0.0

    severity = abs(value) / abs(threshold)

    return min(round(severity, 2), 1.0)


def _detect_harsh_brake(
        payload: dict,
        config: dict
):

    ay = _safe_float(payload.get("ay"))

    threshold = _safe_float(
        config.get("threshold_harsh_brake", -0.4)
    )

    if ay < threshold:

        severity = _calculate_severity(
            ay,
            threshold
        )

        return "harsh_brake", severity

    return "", 0.0


def _detect_harsh_acceleration(
        payload: dict,
        config: dict
):

    ay = _safe_float(payload.get("ay"))

    threshold = _safe_float(
        config.get("threshold_harsh_accel", 0.3)
    )

    if ay > threshold:

        severity = _calculate_severity(
            ay,
            threshold
        )

        return "harsh_acceleration", severity

    return "", 0.0


def _detect_harsh_cornering(
        payload: dict,
        config: dict
):

    ax = _safe_float(payload.get("ax"))

    threshold = _safe_float(
        config.get("threshold_harsh_corner", 0.5)
    )

    if abs(ax) > threshold:

        severity = _calculate_severity(
            abs(ax),
            threshold
        )

        return "harsh_cornering", severity

    return "", 0.0


def _detect_speeding(
        payload: dict,
        config: dict
):

    speed = _safe_float(
        payload.get("speed")
    )

    threshold = _safe_float(
        config.get(
            "threshold_speed_kmh",
            90
        )
    )

    if speed > threshold:

        severity = _calculate_severity(
            speed,
            threshold
        )

        return "speeding", severity

    return "", 0.0


def _detect_idling(
        payload: dict,
        config: dict
):
    """
    packet-level idling

    speed = 0
    rpm > 0
    ignition = ON
    """

    speed = _safe_float(
        payload.get("speed")
    )

    rpm = _safe_float(
        payload.get("rpm")
    )

    ignition = bool(
        payload.get("ignition")
    )

    if (
            ignition
            and speed < 1
            and rpm > 500
    ):

        return "idling", 1.0

    return "", 0.0


EVENT_HANDLERS = (
    _detect_harsh_brake,
    _detect_harsh_acceleration,
    _detect_harsh_cornering,
    _detect_speeding,
    _detect_idling
)


def process_event(
        payload: dict,
        config: dict
) -> dict:
    """
    วิเคราะห์ packet แล้วคืน payload ใหม่

    Pure Function
    """

    new_payload = payload.copy()

    new_payload["event"] = ""
    new_payload["event_severity"] = 0.0

    for handler in EVENT_HANDLERS:

        event_type, severity = handler(
            payload,
            config
        )

        if event_type:

            new_payload["event"] = event_type
            new_payload["event_severity"] = severity

            break

    return new_payload