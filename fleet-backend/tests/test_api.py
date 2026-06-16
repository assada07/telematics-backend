# tests/test_api.py
"""
Integration-style tests สำหรับ Fleet Telematics API
ใช้ TestClient + AsyncMock แทน DB จริง ทำให้รันได้โดยไม่ต้องต่อ TimescaleDB
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# ── Mock config + mqtt ก่อน import app ──────────────────────────────────────
import sys

mock_settings = MagicMock()
mock_settings.DB_USER = "test_user"
mock_settings.DB_PASS = "test_pass"
mock_settings.DB_NAME = "test_db"
mock_settings.DB_HOST = "localhost"
mock_settings.DB_PORT = 5432
mock_settings.MQTT_HOST = "localhost"
mock_settings.MQTT_PORT = 1883
mock_settings.MQTT_USER = "admin"
mock_settings.MQTT_PASS = "public"
mock_settings.MQTT_TOPIC = "fleet/#"
mock_settings.HMAC_SECRET = "test_secret"

sys.modules["app.config"] = MagicMock(settings=mock_settings)
sys.modules["app.services.mqtt_subscriber"] = MagicMock(
    mqtt_subscriber_task=AsyncMock()
)

from app.main import app  # noqa: E402

client = TestClient(app)

VALID_API_KEY = "ktc-fleet-2026-secret"
HEADERS = {"APIKEY": VALID_API_KEY}


# ════════════════════════════════════════════════════════════════════════════
# Helper: สร้าง mock asyncpg record (dict-like)
# ════════════════════════════════════════════════════════════════════════════
def make_record(**kwargs):
    """สร้าง object ที่ behave เหมือน asyncpg Record"""
    record = MagicMock()
    record.__getitem__ = lambda self, key: kwargs[key]
    record.__contains__ = lambda self, key: key in kwargs
    record.keys = lambda: kwargs.keys()
    # ทำให้ dict(record) ทำงานได้
    record.__iter__ = lambda self: iter(kwargs)
    return record


def make_trip_record(**kwargs):
    """asyncpg record สำหรับ trip_logs"""
    defaults = {
        "id": 1,
        "device_id": "DEV001",
        "vehicle_id": 1,
        "driver_id": 1,
        "trip_start": "2026-01-01T08:00:00+07:00",
        "trip_end": "2026-01-01T09:00:00+07:00",
        "distance_km": 45.2,
        "duration_min": 60.0,
        "idle_min": 5.0,
        "max_speed": 110.0,
        "avg_speed": 72.0,
        "harsh_brake_count": 1,
        "harsh_accel_count": 0,
        "harsh_corner_count": 2,
        "speeding_count": 1,
        "driver_score": 88.5,
        "fuel_used": 4.2,
        "gps_track": None,
        "synced_to_odoo": False,
        "created_at": "2026-01-01T09:00:01+07:00",
    }
    defaults.update(kwargs)
    r = MagicMock()
    r.__getitem__ = lambda self, k: defaults[k]
    r.keys = lambda: defaults.keys()
    r.__iter__ = lambda self: iter(defaults)
    return r


# ════════════════════════════════════════════════════════════════════════════
# Root
# ════════════════════════════════════════════════════════════════════════════
class TestRoot:
    def test_root_returns_running(self):
        res = client.get("/")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "running"
        assert "project" in data
        assert "compliance" in data


# ════════════════════════════════════════════════════════════════════════════
# Vehicles — Authentication
# ════════════════════════════════════════════════════════════════════════════
class TestVehicleAuth:
    def test_no_api_key_returns_403(self):
        res = client.get("/api/v1/vehicles/1/location")
        assert res.status_code == 403

    def test_wrong_api_key_returns_403(self):
        res = client.get("/api/v1/vehicles/1/location",
                         headers={"APIKEY": "wrong-key"})
        assert res.status_code == 403

    def test_no_api_key_on_trips_returns_403(self):
        res = client.get("/api/v1/vehicles/DEV001/trips")
        assert res.status_code == 403


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/vehicles/{vehicle_id}/location
# ════════════════════════════════════════════════════════════════════════════
class TestVehicleLocation:

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_location_success(self, mock_conn_fn):
        """ดึงพิกัดรถได้ปกติ"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetchrow.side_effect = [
            make_record(device_id="DEV001"),  # update_status
            make_record(  # telemetry_raw
                ts="2026-01-01T10:00:00+07:00",
                lat=18.796143,
                lon=98.979263,
                speed=60.5,
                heading=90,
                ignition=True,
                event=None,
            ),
        ]
        res = client.get("/api/v1/vehicles/1/location", headers=HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert data["vehicle_id"] == 1
        assert data["device_id"] == "DEV001"
        assert data["lat"] == 18.796143
        assert data["lon"] == 98.979263
        assert data["speed"] == 60.5
        assert data["ignition"] is True
        assert data["event"] is None

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_location_vehicle_not_found(self, mock_conn_fn):
        """ไม่มีรถ ID นั้น → 404"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetchrow.return_value = None
        res = client.get("/api/v1/vehicles/9999/location", headers=HEADERS)
        assert res.status_code == 404
        assert "9999" in res.json()["detail"]

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_location_no_telemetry(self, mock_conn_fn):
        """มีรถแต่ยังไม่มีข้อมูล telemetry → 404"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetchrow.side_effect = [
            make_record(device_id="DEV002"),  # update_status พบ
            None,  # telemetry_raw ว่าง
        ]
        res = client.get("/api/v1/vehicles/2/location", headers=HEADERS)
        assert res.status_code == 404
        assert "DEV002" in res.json()["detail"]

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_location_with_event(self, mock_conn_fn):
        """รถมี event harsh_brake"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetchrow.side_effect = [
            make_record(device_id="DEV003"),
            make_record(
                ts="2026-01-01T11:00:00+07:00",
                lat=13.75,
                lon=100.52,
                speed=95.0,
                heading=180,
                ignition=True,
                event="harsh_brake",
            ),
        ]
        res = client.get("/api/v1/vehicles/3/location", headers=HEADERS)
        assert res.status_code == 200
        assert res.json()["event"] == "harsh_brake"

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_location_db_error(self, mock_conn_fn):
        """DB ล่ม → 500"""
        mock_conn_fn.side_effect = Exception("Connection refused")
        res = client.get("/api/v1/vehicles/1/location", headers=HEADERS)
        assert res.status_code in (500, 403)


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v1/vehicles/{device_id}/trips
# ════════════════════════════════════════════════════════════════════════════
class TestVehicleTrips:

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_trips_empty(self, mock_conn_fn):
        """device ใหม่ยังไม่มีทริป → list ว่าง"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetch.return_value = []
        res = client.get("/api/v1/vehicles/DEV001/trips", headers=HEADERS)
        assert res.status_code == 200
        assert res.json() == []

    @patch("app.api.routes_vehicles.get_db_connection")
    def test_get_trips_returns_list(self, mock_conn_fn):
        """มีทริป 2 อัน → return list 2 items"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetch.return_value = [
            make_trip_record(id=1, driver_score=88.5),
            make_trip_record(id=2, driver_score=92.0),
        ]
        res = client.get("/api/v1/vehicles/DEV001/trips", headers=HEADERS)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2


# ════════════════════════════════════════════════════════════════════════════
# GET /drivers/{driver_id}/bonus
# ════════════════════════════════════════════════════════════════════════════
class TestDriverBonus:

    @patch("app.api.routes_drivers.asyncpg.connect")
    def test_bonus_two_qualified_trips(self, mock_connect):
        """ทริปผ่านเกณฑ์ 2 อัน → โบนัส 100 บาท"""
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.fetch.return_value = [
            make_record(driver_score=90.0),
            make_record(driver_score=70.0),  # ไม่ผ่านเกณฑ์
            make_record(driver_score=88.0),
        ]
        res = client.get("/drivers/D001/bonus")
        assert res.status_code == 200
        data = res.json()
        assert data["driver_id"] == "D001"
        assert data["safe_trips_count"] == 2
        assert data["accumulated_incentive_bonus"] == 100.0
        assert data["currency"] == "THB"
        assert data["odoo_integration_ready"] is True

    @patch("app.api.routes_drivers.asyncpg.connect")
    def test_bonus_no_qualified_trips(self, mock_connect):
        """ไม่มีทริปผ่านเกณฑ์ → โบนัส 0 บาท"""
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.fetch.return_value = [
            make_record(driver_score=80.0),
            make_record(driver_score=75.5),
        ]
        res = client.get("/drivers/D002/bonus")
        assert res.status_code == 200
        data = res.json()
        assert data["safe_trips_count"] == 0
        assert data["accumulated_incentive_bonus"] == 0.0

    @patch("app.api.routes_drivers.asyncpg.connect")
    def test_bonus_all_qualified(self, mock_connect):
        """ทุกทริปผ่านเกณฑ์ → โบนัส = จำนวนทริป × 50"""
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.fetch.return_value = [
            make_record(driver_score=95.0),
            make_record(driver_score=87.0),
            make_record(driver_score=99.0),
            make_record(driver_score=85.0),  # ขอบเกณฑ์พอดี
        ]
        res = client.get("/drivers/D003/bonus")
        assert res.status_code == 200
        assert res.json()["safe_trips_count"] == 4
        assert res.json()["accumulated_incentive_bonus"] == 200.0

    @patch("app.api.routes_drivers.asyncpg.connect")
    def test_bonus_empty_trips(self, mock_connect):
        """คนขับใหม่ยังไม่มีทริป → 0"""
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.fetch.return_value = []
        res = client.get("/drivers/D999/bonus")
        assert res.status_code == 200
        assert res.json()["safe_trips_count"] == 0
        assert res.json()["accumulated_incentive_bonus"] == 0.0

    @patch("app.api.routes_drivers.asyncpg.connect")
    def test_bonus_threshold_boundary(self, mock_connect):
        """84.9 ไม่ผ่าน, 85.0 ผ่าน"""
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.fetch.return_value = [
            make_record(driver_score=84.9),
            make_record(driver_score=85.0),
        ]
        res = client.get("/drivers/D004/bonus")
        assert res.json()["safe_trips_count"] == 1


# ════════════════════════════════════════════════════════════════════════════
# GET /trips/scoring/config
# ════════════════════════════════════════════════════════════════════════════
class TestScoringConfig:

    @patch("app.api.routes_trips.get_db_connection")
    def test_get_config_success(self, mock_conn_fn):
        """มี config active → 200"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetchrow.return_value = make_record(
            id=1,
            config_name="default",
            is_active=True,
            config_data='{"speed_limit": 90}',
            updated_at="2026-01-01T00:00:00+07:00",
        )
        res = client.get("/trips/scoring/config")
        assert res.status_code == 200
        data = res.json()
        assert data["config_name"] == "default"
        assert data["is_active"] is True

    @patch("app.api.routes_trips.get_db_connection")
    def test_get_config_not_found(self, mock_conn_fn):
        """ยังไม่มี config → 404"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.fetchrow.return_value = None
        res = client.get("/trips/scoring/config")
        assert res.status_code == 404

    @patch("app.api.routes_trips.get_db_connection")
    def test_post_config_success(self, mock_conn_fn):
        """บันทึก config ใหม่ → 200 + status success"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.execute.return_value = None
        payload = {
            "speed_limit": 90,
            "harsh_brake_threshold": 0.4,
            "bonus_threshold": 85,
            "bonus_per_trip_thb": 50,
        }
        res = client.post("/trips/scoring/config", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "อัปเดต" in data["message"]

    @patch("app.api.routes_trips.get_db_connection")
    def test_post_config_empty_body(self, mock_conn_fn):
        """ส่ง config เป็น dict ว่าง → ยังควร 200 (valid JSON)"""
        mock_conn = AsyncMock()
        mock_conn_fn.return_value = mock_conn
        mock_conn.execute.return_value = None
        res = client.post("/trips/scoring/config", json={})
        assert res.status_code == 200

    def test_post_config_no_body(self):
        """ไม่ส่ง body → 422 Unprocessable Entity"""
        res = client.post("/trips/scoring/config")
        assert res.status_code == 422
