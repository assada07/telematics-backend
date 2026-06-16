-- ═══════════════════════════════════════════════════════════
-- init.sql — สร้างจาก schema จริงที่ export จากฐานข้อมูล fleet_db
-- วันที่ export: 16 มิถุนายน 2026
-- หมายเหตุ: ไฟล์นี้ตรงกับโครงสร้างที่มีอยู่จริงในระบบ ไม่ใช่การเดา
-- ═══════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ─────────────────────────────────────────────────────────
-- 1. USERS
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50) NOT NULL UNIQUE,
    email           VARCHAR(100) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(100),
    is_active       BOOLEAN DEFAULT true,
    role            VARCHAR(20) DEFAULT 'user',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ─────────────────────────────────────────────────────────
-- 2. API_KEYS
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS api_keys (
    id          SERIAL PRIMARY KEY,
    key_hash    VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(100),
    created_by  INTEGER REFERENCES users(id),
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_used   TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────
-- 3. DEVICES
-- (vehicle_id มี UNIQUE อยู่แล้ว = บังคับ 1 device ต่อ 1 vehicle)
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS devices (
    id              VARCHAR(20) PRIMARY KEY,
    vehicle_id      INTEGER UNIQUE,
    active          BOOLEAN DEFAULT true,
    firmware_ver    VARCHAR(50),
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    driver_id       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_devices_active ON devices(active);
CREATE INDEX IF NOT EXISTS idx_devices_vehicle_id ON devices(vehicle_id)
    WHERE vehicle_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────
-- 4. UPDATE_STATUS
-- PK เป็น composite (vehicle_id, device_id)
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS update_status (
    vehicle_id          INTEGER NOT NULL,
    device_id           VARCHAR(20) NOT NULL REFERENCES devices(id),
    date_update_latest  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (vehicle_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_update_status_device ON update_status(device_id);
CREATE INDEX IF NOT EXISTS idx_update_status_vehicle ON update_status(vehicle_id);

-- ─────────────────────────────────────────────────────────
-- 5. SCORING_CONFIG_CACHE
-- config_name เป็น NOT NULL — ต้องระบุเสมอตอน INSERT
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scoring_config_cache (
    id                      SERIAL PRIMARY KEY,
    config_name             VARCHAR(100) NOT NULL,
    effective_date          DATE,
    score_base              REAL DEFAULT 100.0,
    harsh_brake_deduct      REAL DEFAULT 5.0,
    harsh_accel_deduct      REAL DEFAULT 3.0,
    harsh_corner_deduct     REAL DEFAULT 3.0,
    speeding_deduct         REAL DEFAULT 10.0,
    idling_deduct           REAL DEFAULT 2.0,
    bump_deduct             REAL DEFAULT 4.0,
    max_deduct_per_trip     REAL DEFAULT 50.0,
    harsh_brake_g           REAL DEFAULT 0.40,
    harsh_accel_g           REAL DEFAULT 0.40,
    harsh_corner_g          REAL DEFAULT 0.40,
    speeding_kmh_over       REAL DEFAULT 20.0,
    idle_min_threshold      REAL DEFAULT 5.0,
    synced_from_odoo_at     TIMESTAMPTZ,
    is_active               BOOLEAN DEFAULT false,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scoring_active ON scoring_config_cache(is_active)
    WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_scoring_effective_date ON scoring_config_cache(effective_date DESC);

-- ─────────────────────────────────────────────────────────
-- 6. TELEMETRY_RAW
-- Hypertable พาร์ติชันด้วย ts, PK = (id, ts)
-- ไม่มี vehicle_id — ใช้ device_id เป็นหลัก ตามที่ตั้งใจไว้
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS telemetry_raw (
    id              BIGSERIAL,
    device_id       VARCHAR(20) NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    speed           REAL,
    heading         SMALLINT,
    altitude        REAL,
    hdop            REAL,
    rpm             SMALLINT,
    throttle        REAL,
    engine_load     REAL,
    coolant_temp    REAL,
    fuel_level      REAL,
    ax              REAL,
    ay              REAL,
    az              REAL,
    gx              REAL,
    gy              REAL,
    gz              REAL,
    event           VARCHAR(30),
    event_severity  REAL,
    ignition        BOOLEAN,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    maf_airflow     REAL,
    PRIMARY KEY (id, ts)
);

SELECT create_hypertable(
    'telemetry_raw',
    'ts',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS telemetry_raw_device_id_idx ON telemetry_raw(device_id);
CREATE INDEX IF NOT EXISTS telemetry_raw_ts_idx ON telemetry_raw(ts DESC);
CREATE INDEX IF NOT EXISTS telemetry_raw_event_idx ON telemetry_raw(event);
CREATE INDEX IF NOT EXISTS telemetry_raw_ignition_idx ON telemetry_raw(ignition);

-- ─────────────────────────────────────────────────────────
-- 7. TRIP_LOGS
-- vehicle_id เป็น NOT NULL (ไม่ nullable แบบที่เคยเข้าใจผิด)
-- ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trip_logs (
    id                  BIGSERIAL PRIMARY KEY,
    device_id           VARCHAR(20) NOT NULL REFERENCES devices(id),
    vehicle_id          INTEGER NOT NULL,
    driver_id           INTEGER,
    trip_start          TIMESTAMPTZ NOT NULL,
    trip_end            TIMESTAMPTZ,
    distance_km         REAL,
    duration_min        REAL,
    idle_min            REAL,
    max_speed           REAL,
    avg_speed           REAL,
    harsh_brake_count   SMALLINT DEFAULT 0,
    harsh_accel_count   SMALLINT DEFAULT 0,
    harsh_corner_count  SMALLINT DEFAULT 0,
    speeding_count      SMALLINT DEFAULT 0,
    driver_score        REAL DEFAULT 100.0,
    fuel_used           REAL,
    gps_track           JSONB,
    synced_to_odoo      BOOLEAN DEFAULT false,
    synced_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trip_logs_device ON trip_logs(device_id);
CREATE INDEX IF NOT EXISTS idx_trip_logs_vehicle ON trip_logs(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_trip_logs_driver ON trip_logs(driver_id);
CREATE INDEX IF NOT EXISTS idx_trip_logs_trip_start ON trip_logs(trip_start DESC);
CREATE INDEX IF NOT EXISTS idx_trip_logs_driver_score ON trip_logs(driver_score);
CREATE INDEX IF NOT EXISTS idx_trip_logs_synced ON trip_logs(synced_to_odoo)
    WHERE synced_to_odoo = false;

-- ─────────────────────────────────────────────────────────
-- 8. VIEW: v_driver_monthly_summary
-- ─────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_driver_monthly_summary AS
SELECT
    driver_id,
    to_char(date_trunc('month', trip_start), 'YYYY-MM') AS month,
    count(*) AS total_trips,
    round(avg(driver_score)::numeric, 2) AS avg_score,
    round(sum(distance_km)::numeric, 2) AS total_distance_km,
    round(sum(idle_min)::numeric, 2) AS total_idle_min,
    sum(harsh_brake_count) AS total_harsh_brake,
    sum(harsh_accel_count) AS total_harsh_accel,
    sum(harsh_corner_count) AS total_harsh_corner,
    sum(speeding_count) AS total_speeding,
    sum(CASE WHEN driver_score >= 85 THEN 1 ELSE 0 END) AS safe_trips
FROM trip_logs
WHERE driver_id IS NOT NULL
GROUP BY driver_id, date_trunc('month', trip_start);

-- ═══════════════════════════════════════════════════════════
-- หมายเหตุสำคัญ
-- ═══════════════════════════════════════════════════════════
--
-- 1) ปัญหา error ที่เจอ:
--    "null value in column config_name violates not-null constraint"
--    เกิดจาก INSERT ไม่ได้ระบุ config_name ตรง ๆ ไม่ใช่ schema ผิด
--    ตัวอย่างที่ถูกต้อง:
--
--    INSERT INTO scoring_config_cache (config_name, is_active)
--    VALUES ('default', true);
--
-- 2) devices.vehicle_id มี UNIQUE อยู่แล้ว — ห้าม INSERT ซ้ำ vehicle_id เดิม
--    ถ้า INSERT ซ้ำจะได้ error duplicate key (ถูกต้องตามที่ตั้งใจ)
--
-- 3) telemetry_raw ไม่มี vehicle_id ตามที่ตั้งใจไว้ — ใช้ device_id
--    หากต้องการรู้ vehicle ให้ JOIN ผ่าน update_status หรือ devices
--
-- 4) trip_logs.vehicle_id เป็น NOT NULL — ตอน INSERT trip ใหม่
--    ต้องส่ง vehicle_id มาด้วยเสมอ (backend ต้อง lookup จาก device_id ก่อน)
-- ═══════════════════════════════════════════════════════════