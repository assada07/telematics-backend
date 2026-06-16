# app/services/event_processor.py


def filter_imu_noise_event(ax: float, ay: float, az: float) -> dict:
    """
    วิเคราะห์และกรองสัญญาณรบกวน (Noise Filter) จากข้อมูล G-Force
    ป้องกันความผิดพลาดจากสภาพถนนขรุขระ ก่อนนำไปคิดคะแนนความปลอดภัย
    """
    # เกณฑ์มาตรฐานสากลความปลอดภัยขนส่ง (G-Force Thresholds)
    HARSH_BRAKE_THRESHOLD = -0.4  # แรงเบรกแนวดิ่งเชิงลบ
    HARSH_ACCEL_THRESHOLD = 0.3  # แรงเร่งเครื่องยนต์กระชากไปข้างหน้า
    HARSH_CORNER_THRESHOLD = 0.5  # แรงเหวี่ยงสลัดซ้ายขวาขณะเข้าโค้ง

    return {
        "is_harsh_braking": ay < HARSH_BRAKE_THRESHOLD,
        "is_harsh_acceleration": ay > HARSH_ACCEL_THRESHOLD,
        "is_harsh_cornering": abs(ax) > HARSH_CORNER_THRESHOLD,
    }
