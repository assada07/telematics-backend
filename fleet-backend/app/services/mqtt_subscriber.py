# app/services/mqtt_subscriber.py
import json
import hmac
import hashlib
import asyncio
import logging
import datetime
from aiomqtt import Client, MqttError
import asyncpg
from app.config import settings
from app.services.trip_manager import process_and_save_trip_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MQTT_Subscriber")

# สถานะรถในหน่วยความจำ { device_id: { "is_running": bool, "start_time": datetime } }
ACTIVE_VEHICLE_TRIPS: dict = {}


def verify_hmac(payload_str: str, secret_key: str) -> bool:
    """ตรวจสอบลายเซ็น HMAC-SHA256 ที่ ESP32 แนบมา"""
    try:
        payload_dict = json.loads(payload_str)
        if "sig" not in payload_dict:
            logger.warning("❌ ไม่พบ 'sig' ใน payload")
            return False

        received_sig = payload_dict["sig"]

        target_str = ',"sig":"' + received_sig + '"}'
        if target_str not in payload_str:
            logger.warning("❌ ไม่พบรูปแบบ sig ใน payload string")
            return False

        original_payload_str = payload_str.split(target_str)[0] + "}"

        expected_hmac = hmac.new(
            secret_key.encode("utf-8"),
            original_payload_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(
            received_sig.lower(), expected_hmac.lower())
        if is_valid:
            logger.info("✅ HMAC ผ่าน")
        else:
            logger.warning("❌ HMAC ไม่ตรง — อาจถูกดัดแปลง")
        return is_valid

    except Exception as e:
        logger.error(f"HMAC error: {e}")
        return False


async def save_to_timescaledb(pool: asyncpg.Pool, data: dict):
    """บันทึก telemetry ลง telemetry_raw และ auto-register device"""
    query = """
        INSERT INTO telemetry_raw (
            ts, device_id, lat, lon, speed, heading, altitude, hdop,
            rpm, throttle, engine_load, coolant_temp, fuel_level,
            maf_airflow, ax, ay, az, gx, gy, gz,
            event, event_severity, ignition
        ) VALUES (
            TO_TIMESTAMP($1), $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11, $12, $13,
            $14, $15, $16, $17, $18, $19, $20,
            $21, $22, $23
        );
    """
    try:
        async with pool.acquire() as conn:
            # 1. บันทึก telemetry
            await conn.execute(
                query,
                data.get("ts"),
                data.get("device_id"),
                data.get("lat"),
                data.get("lon"),
                data.get("speed"),
                data.get("heading"),
                data.get("alt"),
                data.get("hdop"),
                data.get("rpm"),
                data.get("throttle"),
                data.get("engine_load"),
                data.get("coolant_temp"),
                data.get("fuel_level"),
                data.get("maf"),
                data.get("ax"),
                data.get("ay"),
                data.get("az"),
                data.get("gx"),
                data.get("gy"),
                data.get("gz"),
                data.get("event", ""),
                data.get("event_severity", 0.0),
                data.get("ignition", True),
            )
            logger.info(
                f"💾 บันทึก {data.get('device_id')} @ ts={data.get('ts')}")

            # 2. Auto-register device ถ้ายังไม่มีใน devices table
            await conn.execute(
                """
                INSERT INTO devices (id, active)
                VALUES ($1, true)
                ON CONFLICT (id) DO NOTHING
            """,
                data.get("device_id"),
            )

    except Exception as e:
        logger.error(f"❌ DB insert error: {e}")


async def mqtt_subscriber_task():
    """Task หลัก: subscribe EMQX → verify → save → trip boundary"""

    db_pool = await asyncpg.create_pool(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASS,
        database=settings.DB_NAME,
        min_size=5,
        max_size=20,
    )

    while True:
        try:
            async with Client(
                hostname=settings.MQTT_HOST,
                port=settings.MQTT_PORT,
                username=settings.MQTT_USER,
                password=settings.MQTT_PASS,
            ) as client:
                logger.info(f"📡 Subscribe: {settings.MQTT_TOPIC}")
                await client.subscribe(settings.MQTT_TOPIC)

                async for message in client.messages:
                    try:
                        payload_str = message.payload.decode("utf-8")

                        # 1. ตรวจ HMAC
                        if not verify_hmac(payload_str, settings.HMAC_SECRET):
                            continue

                        payload = json.loads(payload_str)

                        # 2. บันทึกลง DB
                        await save_to_timescaledb(db_pool, payload)

                        # 3. Trip boundary detection
                        device_id = payload.get("device_id")
                        ignition = payload.get("ignition", True)
                        current_time = datetime.datetime.fromtimestamp(
                            payload.get("ts"), tz=datetime.timezone.utc
                        )

                        if device_id not in ACTIVE_VEHICLE_TRIPS:
                            ACTIVE_VEHICLE_TRIPS[device_id] = {
                                "is_running": ignition,
                                "start_time": current_time,
                            }

                        prev_ignition = ACTIVE_VEHICLE_TRIPS[device_id]["is_running"]

                        if not prev_ignition and ignition:
                            # รถสตาร์ท → เริ่มทริปใหม่
                            ACTIVE_VEHICLE_TRIPS[device_id] = {
                                "is_running": True,
                                "start_time": current_time,
                            }
                            logger.info(f"🎬 [Trip Start] {device_id}")

                        elif prev_ignition and not ignition:
                            # รถดับ → ปิดทริป + คำนวณคะแนน
                            trip_start = ACTIVE_VEHICLE_TRIPS[device_id]["start_time"]
                            ACTIVE_VEHICLE_TRIPS[device_id] = {
                                "is_running": False,
                                "start_time": None,
                            }
                            logger.info(
                                f"🏁 [Trip End] {device_id} — กำลังคำนวณคะแนน..."
                            )

                            asyncio.create_task(
                                process_and_save_trip_summary(
                                    db_pool, device_id, trip_start, current_time
                                )
                            )

                        # อัปเดตสถานะล่าสุด
                        ACTIVE_VEHICLE_TRIPS[device_id]["is_running"] = ignition

                    except json.JSONDecodeError:
                        logger.error("❌ JSON ผิดรูปแบบ")
                    except Exception as e:
                        logger.error(
                            f"❌ Message processing error: {e}", exc_info=True)

        except MqttError as e:
            logger.error(f"⚠️ MQTT หลุด: {e} — retry ใน 5s")
            await asyncio.sleep(5)
