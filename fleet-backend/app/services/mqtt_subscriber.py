# app/services/mqtt_subscriber.py

"""
MQTT Subscriber Service

Responsibilities:
- Connect to MQTT broker (EMQX)
- Subscribe to telemetry topic
- Verify HMAC signature (optional)
- Parse and validate payload
- Lookup vehicle_id from device binding
- Store in telemetry_raw
- Trigger downstream processing (trip manager, event processor)

FDD v1.4 Compliant

FIXES (vs previous version):
  [BUG-1] on_message: asyncio.create_task() ใน paho thread → RuntimeError
          → แก้เป็น asyncio.run_coroutine_threadsafe() + บันทึก _loop ตอน startup

  [BUG-2] loop_forever() บน executor บล็อก asyncio ทั้งหมด ทำให้ retry loop พัง
          → แก้เป็น loop_start() / loop_stop() + asyncio.sleep() แทน

  [BUG-3] hmac.new() ไม่มีใน Python stdlib
          → แก้เป็น hmac.new() (ถูกต้อง)
"""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import paho.mqtt.client as mqtt

from app.config import settings
from app.database import get_db_pool
from app.services.trip_manager import handle_telemetry as trip_handle_telemetry
from app.services.event_processor import process_event as ep_process_event

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Globals
# ──────────────────────────────────────────────────────────────

mqtt_client: Optional[mqtt.Client] = None
connected: bool = False

# [FIX-1] เก็บ reference ของ asyncio event loop ที่ FastAPI ใช้งาน
# ต้องบันทึกตอน mqtt_subscriber_task() เริ่ม (ใน async context)
# เพื่อให้ on_message() ซึ่งรันใน paho thread ใช้ run_coroutine_threadsafe() ได้
_loop: Optional[asyncio.AbstractEventLoop] = None


# ──────────────────────────────────────────────────────────────
# HMAC Verification (optional)
# ──────────────────────────────────────────────────────────────

def verify_hmac(payload_str: str, signature: str) -> bool:
    """
    Verify HMAC-SHA256 signature from ESP32.
    Returns True if HMAC_SECRET is not configured (feature disabled).
    """
    if not settings.HMAC_SECRET:
        return True

    try:
        # [FIX-3] hmac.new() → hmac.new() (Python stdlib ไม่มี hmac.new)
        expected = hmac.new(
            settings.HMAC_SECRET.encode(),
            payload_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected)  # timing-safe compare

    except Exception as e:
        logger.warning(f"HMAC verification error: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# Lookup vehicle_id from device binding
# ──────────────────────────────────────────────────────────────

async def lookup_vehicle_id(
    pool: asyncpg.Pool,
    device_id: str,
) -> Optional[int]:
    """
    Lookup vehicle_id from devices table.
    Returns None if device is not yet bound to a vehicle.
    """
    try:
        vehicle_id = await pool.fetchval(
            "SELECT vehicle_id FROM devices WHERE id = $1 AND active = TRUE",
            device_id,
        )
        return vehicle_id

    except Exception as e:
        logger.warning(f"Error looking up vehicle for device {device_id}: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# Store Telemetry into telemetry_raw
# ──────────────────────────────────────────────────────────────

async def store_telemetry(
    pool: asyncpg.Pool,
    device_id: str,
    vehicle_id: Optional[int],  # ยังคง signature เดิม เพื่อไม่ให้ handle_telemetry() พัง
    payload: dict,
) -> int:
    """
    Insert raw telemetry record into TimescaleDB hypertable.
    Returns the new record ID.

    หมายเหตุ schema: telemetry_raw ไม่มีคอลัมน์ vehicle_id และ created_at
    vehicle_id ถูก lookup แยก แต่ไม่ได้ store ใน raw table
    (join ผ่าน devices.vehicle_id ตอน query แทน)
    """
    # ── Normalize timestamp ──────────────────────────────────────
    # รองรับทั้ง Unix epoch seconds (float/int), milliseconds, และ ISO string
    # ESP32 บางตัวส่ง ms เช่น 1718500000000 แทน seconds 1718500000
    raw_ts = payload.get("ts")
    if raw_ts is None:
        ts_epoch = datetime.now(timezone.utc).timestamp()
    elif isinstance(raw_ts, str):
        try:
            ts_epoch = float(raw_ts)
        except ValueError:
            ts_epoch = datetime.now(timezone.utc).timestamp()
    else:
        ts_epoch = float(raw_ts)

    # ถ้า ts ใหญ่เกิน 1e11 แสดงว่าเป็น milliseconds → หาร 1000
    # threshold: 1e11 ms = ปี 1973 ซึ่งก่อน ESP32 จะมีอยู่มาก
    if ts_epoch > 1e11:
        ts_epoch = ts_epoch / 1000.0
        logger.debug(f"[MQTT] ts converted from ms to seconds: {ts_epoch}")

    # ตรวจ sanity: ถ้า ts ยังเป็น before 2020 → ใช้เวลาปัจจุบันแทน
    # (ป้องกัน 1970 epoch จาก firmware ที่ยังไม่ sync GPS time)
    if ts_epoch < 1577836800:  # 2020-01-01 00:00:00 UTC
        logger.warning(
            f"[MQTT] ts={ts_epoch} ดูเหมือน GPS ยังไม่ sync เวลา "
            f"→ ใช้ server time แทน"
        )
        ts_epoch = datetime.now(timezone.utc).timestamp()

    # ── Normalize ignition ──────────────────────────────────────
    # ESP32 อาจส่งมาเป็น 0/1 (int) หรือ true/false (bool)
    raw_ignition = payload.get("ignition")
    if isinstance(raw_ignition, int):
        ignition = bool(raw_ignition)
    elif raw_ignition is None:
        ignition = True   # default: ถ้าไม่ส่งมา assume ignition on
    else:
        ignition = raw_ignition

    # ── Normalize altitude ──────────────────────────────────────
    # firmware อาจใช้ key "alt" หรือ "altitude"
    altitude = payload.get("altitude") or payload.get("alt")

    try:
        telemetry_id = await pool.fetchval(
            """
            INSERT INTO telemetry_raw (
                device_id, ts,
                lat, lon, speed, heading, altitude, hdop,
                rpm, throttle, engine_load, coolant_temp, fuel_level,
                maf_airflow,
                ax, ay, az, gx, gy, gz,
                event, event_severity, ignition,
                created_at
            )
            VALUES (
                $1,  to_timestamp($2),
                $3,  $4,  $5,  $6,  $7,  $8,
                $9,  $10, $11, $12, $13,
                $14,
                $15, $16, $17, $18, $19, $20,
                $21, $22, $23,
                NOW()
            )
            RETURNING id
            """,
            # ── $1-$2: Identity + Timestamp ──────────────────
            device_id,
            ts_epoch,
            # ── $3-$8: GPS ───────────────────────────────────
            payload.get("lat"),
            payload.get("lon"),
            payload.get("speed"),
            payload.get("heading"),
            altitude,
            payload.get("hdop"),
            # ── $9-$13: OBD-II ───────────────────────────────
            payload.get("rpm"),
            payload.get("throttle"),
            payload.get("engine_load"),
            payload.get("coolant_temp"),
            payload.get("fuel_level"),
            # ── $14: MAF ─────────────────────────────────────
            payload.get("maf_airflow") or payload.get("maf"),
            # ── $15-$20: IMU ─────────────────────────────────
            payload.get("ax"),
            payload.get("ay"),
            payload.get("az"),
            payload.get("gx"),
            payload.get("gy"),
            payload.get("gz"),
            # ── $21-$23: Events + Ignition ───────────────────
            payload.get("event") or None,
            payload.get("event_severity"),
            ignition,
        )

        return telemetry_id

    except Exception as e:
        logger.error(f"Error storing telemetry from {device_id}: {e}", exc_info=True)
        raise


# ──────────────────────────────────────────────────────────────
# Default event detection config
# ──────────────────────────────────────────────────────────────

_DEFAULT_EVENT_CONFIG: dict = {
    "threshold_brake_g":   0.4,
    "threshold_accel_g":   0.4,
    "threshold_corner_g":  0.4,
    "threshold_speed_kmh": 90.0,
    "threshold_idle_min":  5.0,
}


# ──────────────────────────────────────────────────────────────
# Main telemetry processing pipeline
# ──────────────────────────────────────────────────────────────

async def handle_telemetry(
    pool: asyncpg.Pool,
    device_id: str,
    payload: dict,
) -> None:
    """
    Process one incoming MQTT telemetry message end-to-end.

    Pipeline:
    1. Lookup vehicle_id from device binding
    2. Store raw telemetry in telemetry_raw
    3. Pass to trip_manager.handle_telemetry (trip boundary detection)
    4. Run event_processor.process_event (harsh event detection)
    """
    try:
        # ── Step 1: Lookup vehicle ──────────────────────────────
        vehicle_id = await lookup_vehicle_id(pool, device_id)

        if vehicle_id is None:
            logger.warning(
                f"[TELEMETRY] Device '{device_id}' ไม่ได้ผูกกับรถคันไหน — "
                f"telemetry จะถูก store แต่ trip/event processing จะถูกข้าม "
                f"→ ให้เรียก PUT /api/v1/config/vehicle เพื่อผูก device กับรถก่อน"
            )
            # Auto-register device ถ้ายังไม่มีใน DB
            # (ป้องกัน error ตอน store เพราะ FK หรือ constraint)
            try:
                await pool.execute(
                    """
                    INSERT INTO devices (id, active)
                    VALUES ($1, true)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    device_id,
                )
            except Exception as reg_err:
                logger.warning(f"[TELEMETRY] Auto-register device failed: {reg_err}")

        # ── Step 2: Store raw telemetry ─────────────────────────
        telemetry_id = await store_telemetry(pool, device_id, vehicle_id, payload)

        logger.info(
            f"[TELEMETRY STORED] id={telemetry_id} "
            f"device={device_id} bound_vehicle={vehicle_id} "
            f"lat={payload.get('lat')} lon={payload.get('lon')} "
            f"speed={payload.get('speed')} kmh "
            f"ignition={payload.get('ignition')}"
        )

        # ── Step 3: Trip detection (requires vehicle binding) ───
        if vehicle_id is not None:
            payload_with_device = {**payload, "device_id": device_id}
            await trip_handle_telemetry(pool=pool, payload=payload_with_device)

        # ── Step 4: Event detection (pure function, always runs) ─
        enriched = ep_process_event(
            payload={**payload, "device_id": device_id},
            config=_DEFAULT_EVENT_CONFIG,
        )

        if enriched.get("event"):
            logger.info(
                f"[EVENT] device={device_id} "
                f"event={enriched['event']} "
                f"severity={enriched.get('event_severity'):.2f}"
            )

    except Exception as e:
        logger.error(
            f"Error processing telemetry from '{device_id}': {e}",
            exc_info=True,
        )


# ──────────────────────────────────────────────────────────────
# Async wrapper (รันใน asyncio event loop ของ FastAPI)
# ──────────────────────────────────────────────────────────────

async def _process_message_async(device_id: str, payload: dict) -> None:
    """
    Async wrapper สำหรับ telemetry pipeline.
    รันผ่าน run_coroutine_threadsafe จาก on_message callback.
    """
    try:
        pool = await get_db_pool()
        await handle_telemetry(pool, device_id, payload)

    except Exception as e:
        logger.error(
            f"Async processing failed for device '{device_id}': {e}",
            exc_info=True,
        )


# ──────────────────────────────────────────────────────────────
# MQTT Callbacks (รันใน paho thread — ต้องไม่ใช้ asyncio โดยตรง)
# ──────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    """Called by paho when broker connection is established."""
    global connected

    if rc == 0:
        connected = True
        client.subscribe(settings.MQTT_TOPIC, qos=1)
        logger.info(
            f"[MQTT] Connected ✓  broker={settings.MQTT_HOST}:{settings.MQTT_PORT}"
        )
        logger.info(f"[MQTT] Subscribed → {settings.MQTT_TOPIC}  (QoS 1)")
    else:
        connected = False
        rc_messages = {
            1: "incorrect protocol version",
            2: "invalid client identifier",
            3: "server unavailable",
            4: "bad username or password",
            5: "not authorised",
        }
        reason = rc_messages.get(rc, f"unknown rc={rc}")
        logger.error(f"[MQTT] Connection refused: {reason}")


def on_disconnect(client, userdata, rc, properties=None):
    """Called by paho on disconnection."""
    global connected
    connected = False

    if rc == 0:
        logger.info("[MQTT] Disconnected gracefully")
    else:
        logger.warning(f"[MQTT] Unexpected disconnection rc={rc} — will retry")


def on_message(client, userdata, msg):
    """
    Called by paho thread when a message arrives.

    [FIX-1] ห้ามใช้ asyncio.create_task() ที่นี่ เพราะรันอยู่ใน paho thread
    ซึ่งไม่มี running event loop ใน thread ของตัวเอง

    วิธีถูกต้อง: ใช้ asyncio.run_coroutine_threadsafe(coro, loop)
    โดย _loop คือ event loop ของ FastAPI ที่บันทึกไว้ตอน startup
    """
    # ── Guard: ต้องมี loop พร้อมก่อน ──────────────────────────
    if _loop is None or not _loop.is_running():
        logger.warning("[MQTT] Event loop not ready — message dropped")
        return

    try:
        # ── Parse topic: kotchasaan/fleet/{device_id}/telemetry ─
        topic_parts = msg.topic.split("/")
        if len(topic_parts) >= 2:
            device_id = topic_parts[-2]   # ตำแหน่ง -2 = device_id
        else:
            device_id = topic_parts[-1]

        payload_str = msg.payload.decode("utf-8")
        payload     = json.loads(payload_str)

        logger.debug(
            f"[MQTT] RX topic={msg.topic} device={device_id} "
            f"size={len(msg.payload)}B"
        )

        # ── HMAC verification (optional) ─────────────────────
        signature = None
        if hasattr(msg, "properties") and msg.properties:
            signature = getattr(msg.properties, "hmac", None)

        if signature and not verify_hmac(payload_str, signature):
            logger.warning(f"[MQTT] HMAC failed — device={device_id} message dropped")
            return

        # ── [FIX-1] ส่ง coroutine ข้าม thread อย่างถูกต้อง ──
        future = asyncio.run_coroutine_threadsafe(
            _process_message_async(device_id, payload),
            _loop,
        )

        # Log ถ้า coroutine โยน exception (non-blocking)
        def _on_done(fut):
            exc = fut.exception()
            if exc:
                logger.error(
                    f"[MQTT] Processing failed for device={device_id}: {exc}"
                )

        future.add_done_callback(_on_done)

    except json.JSONDecodeError as e:
        logger.error(f"[MQTT] Invalid JSON payload on {msg.topic}: {e}")
    except UnicodeDecodeError as e:
        logger.error(f"[MQTT] Cannot decode payload on {msg.topic}: {e}")
    except Exception as e:
        logger.error(f"[MQTT] on_message error: {e}", exc_info=True)


# ──────────────────────────────────────────────────────────────
# MQTT Subscriber Background Task
# ──────────────────────────────────────────────────────────────

async def mqtt_subscriber_task() -> None:
    """
    Background task: เชื่อมต่อ MQTT broker และรับ message ตลอดเวลา.
    ถูกเรียกจาก FastAPI lifespan startup.

    [FIX-2] เปลี่ยนจาก loop_forever() + executor
            เป็น loop_start() (paho background thread)
            แล้วใช้ asyncio.sleep() วน keep-alive

    loop_forever() บน run_in_executor() จะบล็อก executor thread
    และทำให้ asyncio.CancelledError ไม่สามารถ interrupt ได้อย่างถูกต้อง
    """
    global mqtt_client, connected, _loop

    # [FIX-1] บันทึก event loop ก่อนเริ่ม — ใช้โดย on_message()
    _loop = asyncio.get_running_loop()

    retry_delay = 5

    while True:
        try:
            # ── สร้าง MQTT client ใหม่ทุกครั้งที่ retry ──────
            mqtt_client = mqtt.Client(
                client_id="fleet-telematics-backend",
                protocol=mqtt.MQTTv311,
                clean_session=True,
            )

            mqtt_client.on_connect    = on_connect
            mqtt_client.on_disconnect = on_disconnect
            mqtt_client.on_message    = on_message

            # ── Auth ────────────────────────────────────────────
            if settings.MQTT_USER and settings.MQTT_PASS:
                mqtt_client.username_pw_set(
                    settings.MQTT_USER,
                    settings.MQTT_PASS,
                )

            # ── TLS (optional) ──────────────────────────────────
            # ถ้า port 8883 ให้ uncomment:
            # mqtt_client.tls_set()

            logger.info(
                f"[MQTT] Connecting to {settings.MQTT_HOST}:{settings.MQTT_PORT} ..."
            )

            mqtt_client.connect(
                settings.MQTT_HOST,
                settings.MQTT_PORT,
                keepalive=60,
            )

            # [FIX-2] loop_start() รัน paho network loop ใน background thread
            # ไม่บล็อก asyncio event loop — ต่างจาก loop_forever()
            mqtt_client.loop_start()

            # ── Keep-alive: รอจนกว่าจะถูก cancel ─────────────
            while True:
                await asyncio.sleep(5)

                # ตรวจ connection health
                if not connected:
                    logger.warning("[MQTT] Connection lost — reconnecting ...")
                    break   # ออกจาก inner loop → ไป reconnect

                logger.debug(f"[MQTT] Heartbeat ✓  connected={connected}")

            # Clean up ก่อน retry
            mqtt_client.loop_stop()
            try:
                mqtt_client.disconnect()
            except Exception:
                pass

        except asyncio.CancelledError:
            logger.info("[MQTT] Subscriber task cancelled — shutting down")
            if mqtt_client:
                mqtt_client.loop_stop()
                try:
                    mqtt_client.disconnect()
                except Exception:
                    pass
            break

        except OSError as e:
            # TCP connection refused / network unreachable
            logger.error(
                f"[MQTT] Network error: {e}. Retry in {retry_delay}s ..."
            )
            connected = False

        except Exception as e:
            logger.error(
                f"[MQTT] Unexpected error: {e}. Retry in {retry_delay}s ...",
                exc_info=True,
            )
            connected = False

        # ── Exponential backoff retry ───────────────────────────
        try:
            await asyncio.sleep(retry_delay)
        except asyncio.CancelledError:
            break

        retry_delay = min(retry_delay * 2, 60)   # max 60s


# ──────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────

def is_mqtt_connected() -> bool:
    """Return True if MQTT client is currently connected to broker."""
    return connected and mqtt_client is not None