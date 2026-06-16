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

# ── Import functions โดยตรง (ไม่ใช่ object) ───────────────────
from app.services.trip_manager import handle_telemetry as trip_handle_telemetry
from app.services.event_processor import process_event as ep_process_event

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# MQTT Client (Global)
# ──────────────────────────────────────────────────────────────

mqtt_client: Optional[mqtt.Client] = None
connected: bool = False


# ──────────────────────────────────────────────────────────────
# HMAC Verification (optional)
# ──────────────────────────────────────────────────────────────

def verify_hmac(payload_str: str, signature: str) -> bool:
    """
    Verify HMAC-SHA256 signature from ESP32.

    Returns True if HMAC_SECRET not configured (disabled).
    """

    if not settings.HMAC_SECRET:
        return True

    try:
        expected = hmac.new(
            settings.HMAC_SECRET.encode(),
            payload_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        return signature == expected

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
            "SELECT vehicle_id FROM devices WHERE id = $1",
            device_id,
        )
        return vehicle_id

    except Exception as e:
        logger.warning(
            f"Error looking up vehicle for device {device_id}: {e}"
        )
        return None


# ──────────────────────────────────────────────────────────────
# Store Telemetry into telemetry_raw
# ──────────────────────────────────────────────────────────────

async def store_telemetry(
    pool: asyncpg.Pool,
    device_id: str,
    vehicle_id: Optional[int],
    payload: dict,
) -> int:
    """
    Insert raw telemetry record into TimescaleDB.

    Returns the new record ID.
    """

    try:
        telemetry_id = await pool.fetchval(
            """
            INSERT INTO telemetry_raw (
                device_id, vehicle_id, ts,
                lat, lon, speed, heading, altitude, hdop,
                rpm, throttle, engine_load, coolant_temp, fuel_level,
                ax, ay, az, gx, gy, gz,
                event, event_severity, ignition,
                created_at
            )
            VALUES (
                $1,  $2,  to_timestamp($3),
                $4,  $5,  $6,  $7,  $8,  $9,
                $10, $11, $12, $13, $14,
                $15, $16, $17, $18, $19, $20,
                $21, $22, $23,
                NOW()
            )
            RETURNING id
            """,
            device_id,
            vehicle_id,
            payload.get("ts", datetime.now(timezone.utc).timestamp()),
            # GPS
            payload.get("lat"),
            payload.get("lon"),
            payload.get("speed"),
            payload.get("heading"),
            payload.get("altitude"),
            payload.get("hdop"),
            # OBD-II
            payload.get("rpm"),
            payload.get("throttle"),
            payload.get("engine_load"),
            payload.get("coolant_temp"),
            payload.get("fuel_level"),
            # IMU
            payload.get("ax"),
            payload.get("ay"),
            payload.get("az"),
            payload.get("gx"),
            payload.get("gy"),
            payload.get("gz"),
            # Events
            payload.get("event"),
            payload.get("event_severity"),
            payload.get("ignition"),
        )

        return telemetry_id

    except Exception as e:
        logger.error(f"Error storing telemetry: {e}", exc_info=True)
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
    Process one incoming MQTT telemetry message.

    Flow:
    1. Lookup vehicle_id from device binding
    2. Store in telemetry_raw
    3. Pass to trip_manager.handle_telemetry (trip boundary detection)
    4. Run event_processor.process_event (harsh events detection)
    """

    try:
        # ── Step 1: Lookup vehicle_id ──────────────────────────
        vehicle_id = await lookup_vehicle_id(pool, device_id)

        if vehicle_id is None:
            logger.warning(
                f"Device {device_id} not yet bound to vehicle. "
                f"Telemetry stored but trip processing skipped."
            )

        # ── Step 2: Store raw telemetry ────────────────────────
        telemetry_id = await store_telemetry(
            pool, device_id, vehicle_id, payload
        )

        logger.debug(
            f"Stored telemetry id={telemetry_id} "
            f"device={device_id} vehicle={vehicle_id}"
        )

        # ── Step 3: Trip detection (requires device binding) ───
        if vehicle_id is not None:

            # trip_manager.handle_telemetry รับ (pool, payload)
            # device_id ต้องอยู่ใน payload แล้ว
            payload_with_device = {**payload, "device_id": device_id}

            await trip_handle_telemetry(
                pool=pool,
                payload=payload_with_device,
            )

        # ── Step 4: Event detection (pure function) ────────────
        enriched = ep_process_event(
            payload={**payload, "device_id": device_id},
            config=_DEFAULT_EVENT_CONFIG,
        )

        if enriched.get("event"):
            logger.debug(
                f"Event detected: device={device_id} "
                f"event={enriched['event']} "
                f"severity={enriched.get('event_severity')}"
            )

    except Exception as e:
        logger.error(
            f"Error processing telemetry from {device_id}: {e}",
            exc_info=True,
        )


# ──────────────────────────────────────────────────────────────
# MQTT Callbacks
# ──────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT connected callback"""

    global connected

    if rc == 0:
        logger.info("MQTT client connected successfully")
        connected = True
        client.subscribe(settings.MQTT_TOPIC)
        logger.info(f"Subscribed to topic: {settings.MQTT_TOPIC}")
    else:
        logger.error(f"MQTT connection failed with code {rc}")
        connected = False


def on_disconnect(client, userdata, rc, properties=None):
    """MQTT disconnected callback"""

    global connected

    if rc != 0:
        logger.warning(f"Unexpected MQTT disconnection: rc={rc}")
    else:
        logger.info("MQTT client disconnected gracefully")

    connected = False


def on_message(client, userdata, msg):
    """MQTT message received — schedule async processing"""

    try:
        # Extract device_id from topic pattern: .../DEVICE_ID/...
        topic_parts = msg.topic.split("/")
        device_id = topic_parts[-2] if len(topic_parts) >= 2 else topic_parts[-1]

        payload_str = msg.payload.decode("utf-8")
        payload = json.loads(payload_str)

        # HMAC verification (optional)
        signature = None
        if hasattr(msg, "properties") and msg.properties:
            signature = getattr(msg.properties, "hmac", None)

        if signature and not verify_hmac(payload_str, signature):
            logger.warning(f"HMAC verification failed for device {device_id}")
            return

        # Schedule async processing
        asyncio.create_task(
            _process_message_async(device_id, payload),
            name=f"telemetry-{device_id}",
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse MQTT message: {e}")
    except Exception as e:
        logger.error(f"Error in on_message: {e}", exc_info=True)


# ──────────────────────────────────────────────────────────────
# Async message processing (background)
# ──────────────────────────────────────────────────────────────

async def _process_message_async(device_id: str, payload: dict) -> None:
    """Run telemetry pipeline in async context"""

    try:
        pool = await get_db_pool()
        await handle_telemetry(pool, device_id, payload)

    except Exception as e:
        logger.error(
            f"Error in async message processing for {device_id}: {e}",
            exc_info=True,
        )


# ──────────────────────────────────────────────────────────────
# MQTT Subscriber Background Task
# ──────────────────────────────────────────────────────────────

async def mqtt_subscriber_task() -> None:
    """
    Background task: connect to MQTT broker and process messages.

    Called during FastAPI lifespan startup.
    Retries on connection failure.
    """

    global mqtt_client, connected

    retry_delay = 5

    while True:

        try:
            mqtt_client = mqtt.Client(
                client_id="fleet-telematics-backend",
                protocol=mqtt.MQTTv311,
            )

            mqtt_client.on_connect    = on_connect
            mqtt_client.on_disconnect = on_disconnect
            mqtt_client.on_message    = on_message

            if settings.MQTT_USER and settings.MQTT_PASS:
                mqtt_client.username_pw_set(
                    settings.MQTT_USER,
                    settings.MQTT_PASS,
                )

            logger.info(
                f"Connecting to MQTT broker: "
                f"{settings.MQTT_HOST}:{settings.MQTT_PORT}"
            )

            mqtt_client.connect(
                settings.MQTT_HOST,
                settings.MQTT_PORT,
                keepalive=60,
            )

            # Run paho network loop in executor (non-blocking)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, mqtt_client.loop_forever)

        except asyncio.CancelledError:
            logger.info("MQTT subscriber task cancelled")
            if mqtt_client:
                mqtt_client.disconnect()
            break

        except Exception as e:
            logger.error(
                f"MQTT connection error: {e}. "
                f"Retrying in {retry_delay}s...",
                exc_info=True,
            )
            connected = False

            try:
                await asyncio.sleep(retry_delay)
            except asyncio.CancelledError:
                break

            retry_delay = min(retry_delay * 2, 60)

        finally:
            if mqtt_client:
                try:
                    mqtt_client.disconnect()
                except Exception:
                    pass


# ──────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────

def is_mqtt_connected() -> bool:
    """Return True if MQTT client is currently connected"""
    return connected and mqtt_client is not None