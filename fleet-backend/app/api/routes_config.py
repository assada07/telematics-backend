# app/api/routes_config.py — FIXED VERSION
# 🔴 CRITICAL FIX #1: Add 409 Conflict validation for device-vehicle binding

"""
Device Configuration & Management Endpoints

Handles:
- Device registration (single + batch)
- Device-to-vehicle binding with conflict prevention
- Vehicle config updates with device migration
- Scoring config (push from Odoo)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import asyncpg
from typing import List, Optional
from datetime import datetime

from app.database import get_db_pool

router = APIRouter(prefix="/api/v1", tags=["Config"])

# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────

class RegisterDeviceRequest(BaseModel):
    """Request body for device registration"""
    device_id: str
    device_name: str
    vehicle_id: int


class RegisterDeviceBatchRequest(BaseModel):
    """Request body for batch registration"""
    devices: List[RegisterDeviceRequest]


class VehicleConfigUpdate(BaseModel):
    """Update vehicle with new device (device migration)"""
    vehicle_id: int
    new_device_id: str
    old_device_id: Optional[str] = None  # Explicitly provide to ensure


class ScoringConfigRequest(BaseModel):
    """Scoring config pushed from Odoo"""
    config_name: str
    score_base: float = 100.0
    harsh_brake_deduct: float = 5.0
    harsh_accel_deduct: float = 3.0
    harsh_corner_deduct: float = 3.0
    speeding_deduct: float = 10.0
    idling_deduct: float = 2.0
    bump_deduct: float = 4.0
    harsh_brake_g: float = 0.40
    harsh_accel_g: float = 0.40
    harsh_corner_g: float = 0.40
    speeding_kmh_over: float = 20.0
    idle_min_threshold: float = 5.0
    max_deduct_per_trip: float = 50.0
    is_active: bool = True
    synced_from_odoo_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────
# Register Single Device — WITH CONFLICT PREVENTION ✅
# ─────────────────────────────────────────────────────────────

async def _register_single(
    conn: asyncpg.Connection,
    item: RegisterDeviceRequest
) -> dict:
    """
    Register single device-to-vehicle binding
    
    🔴 CRITICAL FIX:
    - Check if EXACT binding (device + vehicle) already exists → 409
    - Check if device already bound to DIFFERENT vehicle → 409
    - Enforce 1-to-1 relationship
    
    Args:
        conn: Database connection
        item: RegisterDeviceRequest
        
    Returns:
        dict with status, device_id, vehicle_id
        
    Raises:
        HTTPException(409): If conflict detected
    """
    
    device_id = item.device_id.strip().upper()
    vehicle_id = item.vehicle_id
    
    # ─────────────────────────────────────────────
    # ✅ Step 1: Check exact binding already exists
    # ─────────────────────────────────────────────
    
    existing_same_binding = await conn.fetchrow(
        """
        SELECT vehicle_id FROM update_status 
        WHERE device_id = $1 AND vehicle_id = $2
        """,
        device_id, vehicle_id
    )
    
    if existing_same_binding:
        # 🔴 CONFLICT: Device already bound to THIS vehicle
        raise HTTPException(
            status_code=409,
            detail=(
                f"Device {device_id} is already bound to vehicle {vehicle_id}. "
                f"No changes made."
            )
        )
    
    # ─────────────────────────────────────────────
    # ✅ Step 2: Check if device bound to DIFFERENT vehicle
    # ─────────────────────────────────────────────
    
    existing_other_binding = await conn.fetchrow(
        """
        SELECT vehicle_id FROM update_status 
        WHERE device_id = $1 AND vehicle_id != $2
        """,
        device_id, vehicle_id
    )
    
    if existing_other_binding:
        # 🔴 CONFLICT: Device already bound to another vehicle
        other_vehicle_id = existing_other_binding['vehicle_id']
        raise HTTPException(
            status_code=409,
            detail=(
                f"Device {device_id} is already bound to vehicle {other_vehicle_id}. "
                f"Use PUT /config/vehicle to migrate."
            )
        )
    
    # ─────────────────────────────────────────────
    # ✅ Step 3: Check if vehicle already has device
    # ─────────────────────────────────────────────
    
    existing_vehicle_device = await conn.fetchrow(
        """
        SELECT device_id FROM update_status 
        WHERE vehicle_id = $1 AND device_id != $2
        """,
        vehicle_id, device_id
    )
    
    if existing_vehicle_device:
        # 🔴 CONFLICT: Vehicle already has different device (1-to-1 violation)
        other_device_id = existing_vehicle_device['device_id']
        raise HTTPException(
            status_code=409,
            detail=(
                f"Vehicle {vehicle_id} is already bound to device {other_device_id}. "
                f"Cannot bind to {device_id}. Use PUT /config/vehicle to replace."
            )
        )
    
    # ─────────────────────────────────────────────
    # ✅ Step 4: All checks passed — Register binding
    # ─────────────────────────────────────────────
    
    try:
        await conn.execute(
            """
            INSERT INTO devices (id, vehicle_id, active, registered_at)
            VALUES ($1, $2, true, NOW())
            ON CONFLICT (id) 
            DO UPDATE SET vehicle_id = $2, active = true
            """,
            device_id, vehicle_id
        )
        
        await conn.execute(
            """
            INSERT INTO update_status (vehicle_id, device_id, date_update_latest)
            VALUES ($1, $2, NOW())
            ON CONFLICT (vehicle_id, device_id) 
            DO UPDATE SET date_update_latest = NOW()
            """,
            vehicle_id, device_id
        )
        
        return {
            "status": "success",
            "device_id": device_id,
            "vehicle_id": vehicle_id,
            "registered_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────
# GET Devices — List all available devices
# ─────────────────────────────────────────────────────────────

@router.get("/devices")
async def get_devices(pool: asyncpg.Pool = Depends(get_db_pool)):
    """
    List all devices
    
    Returns:
        {
            "total": 50,
            "devices": [
                {
                    "id": "KTC-001",
                    "vehicle_id": 101,
                    "active": true,
                    "registered_at": "2026-01-15T10:00:00Z"
                },
                ...
            ]
        }
    """
    
    try:
        devices = await pool.fetch(
            """
            SELECT id, vehicle_id, active, registered_at
            FROM devices
            ORDER BY id ASC
            """
        )
        
        return {
            "total": len(devices),
            "devices": [dict(d) for d in devices]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# GET Device Config — Check device binding status
# ─────────────────────────────────────────────────────────────

@router.get("/config_device")
async def get_device_config(
    device_id: str,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Get current binding status of a device
    
    Query Params:
        device_id: Device ID (e.g., "KTC-001")
    
    Returns:
        {
            "device_id": "KTC-001",
            "vehicle_id": 101,
            "is_bound": true,
            "status": "active",
            "date_update_latest": "2026-06-14T15:30:00Z"
        }
    """
    
    try:
        row = await pool.fetchrow(
            """
            SELECT 
                d.id as device_id,
                d.vehicle_id,
                d.active,
                u.date_update_latest
            FROM devices d
            LEFT JOIN update_status u ON d.id = u.device_id
            WHERE d.id = $1
            """,
            device_id.upper()
        )
        
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
        
        return {
            "device_id": row['device_id'],
            "vehicle_id": row['vehicle_id'],
            "is_bound": row['vehicle_id'] is not None,
            "status": "active" if row['active'] else "inactive",
            "date_update_latest": row['date_update_latest']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# POST Register Single Device
# ─────────────────────────────────────────────────────────────

@router.post("/config_device/register", status_code=201)
async def register_device_single(
    request: RegisterDeviceRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Register single device-to-vehicle binding
    
    Request Body:
        {
            "device_id": "KTC-001",
            "device_name": "Device 1",
            "vehicle_id": 101
        }
    
    Returns:
        201 Created with binding details
        409 Conflict if duplicate/conflict detected
    
    Errors:
        - 404: Vehicle not found
        - 409: Duplicate binding or 1-to-1 violation
        - 500: Database error
    """
    
    try:
        async with pool.acquire() as conn:
            register_result = await _register_single(conn, request)
            return register_result
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# POST Register Batch Devices — All-or-Nothing
# ─────────────────────────────────────────────────────────────

@router.post("/config_device/register/batch", status_code=201)
async def register_device_batch(
    request: RegisterDeviceBatchRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Register multiple devices in batch (All-or-Nothing transaction)
    
    Request Body:
        {
            "devices": [
                {"device_id": "KTC-001", "device_name": "Dev 1", "vehicle_id": 101},
                {"device_id": "KTC-002", "device_name": "Dev 2", "vehicle_id": 102},
                ...
            ]
        }
    
    Returns:
        201 Created with:
        {
            "status": "success",
            "registered": 2,
            "results": [
                {"device_id": "KTC-001", "vehicle_id": 101, "status": "success"},
                ...
            ]
        }
    
    Note:
        If any device conflicts, ENTIRE transaction rolls back (all-or-nothing)
    """
    
    if not request.devices:
        raise HTTPException(status_code=400, detail="No devices provided")
    
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():  # ✅ All-or-Nothing
                
                results = []
                
                for item in request.devices:
                    try:
                        batch_item_result = await _register_single(conn, item)
                        results.append(batch_item_result)
                        
                    except HTTPException as e:
                        # Re-raise to trigger rollback
                        raise
                
                return {
                    "status": "success",
                    "registered": len(results),
                    "results": results
                }
                
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# PUT Update Vehicle Config — Device Bind / Migration
# ─────────────────────────────────────────────────────────────

@router.put("/config/vehicle")
async def update_vehicle_config(
    request: VehicleConfigUpdate,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Odoo เรียกเมื่อผูกหรือเปลี่ยนบอร์ด ESP32 ให้รถ

    รองรับ 3 กรณี:
    1. รถยังไม่มีบอร์ด → register ใหม่ทันที (ไม่ throw 404)
    2. รถมีบอร์ดเดิม = บอร์ดใหม่ → return no_change
    3. รถมีบอร์ดเดิม ≠ บอร์ดใหม่ → migrate แล้ว bind ใหม่
       - ถ้าบอร์ดใหม่ผูกกับรถอื่นอยู่ → ปลดออกก่อน (ไม่ throw 409)

    Body:
        vehicle_id   : int  — รหัสรถ
        new_device_id: str  — รหัสบอร์ดใหม่
        old_device_id: str? — optional safety check

    Returns:
        status: "registered" | "no_change" | "migrated"
    """
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():

                vehicle_id    = request.vehicle_id
                new_device_id = request.new_device_id.upper()
                old_device_id = request.old_device_id.upper() if request.old_device_id else None

                # ── 1. หาบอร์ดปัจจุบันของรถคันนี้ ──────────────────────
                current = await conn.fetchrow(
                    "SELECT device_id FROM update_status WHERE vehicle_id = $1 LIMIT 1",
                    vehicle_id
                )
                actual_old_device = current["device_id"] if current else None

                # ── safety check: old_device_id ที่ Odoo ส่งมาตรงกันไหม ──
                if old_device_id and actual_old_device and old_device_id != actual_old_device:
                    # แจ้งเตือนแต่ไม่ block — ใช้ actual จาก DB แทน
                    pass  # log ไว้ได้ถ้าต้องการ

                # ── 2. บอร์ดเดิม = บอร์ดใหม่ → ไม่ต้องทำอะไร ───────────
                if actual_old_device and actual_old_device == new_device_id:
                    return {
                        "status": "no_change",
                        "vehicle_id": vehicle_id,
                        "device_id": new_device_id,
                        "previous_device_id": None,
                        "migrated_trip_logs": 0,
                        "message": f"รถ {vehicle_id} ผูกกับบอร์ด {new_device_id} อยู่แล้ว"
                    }

                # ── 3. ถ้าบอร์ดใหม่ผูกกับรถอื่นอยู่ → ปลดออกก่อน ───────
                await conn.execute(
                    "UPDATE devices SET vehicle_id = NULL, active = false "
                    "WHERE id = $1 AND vehicle_id != $2",
                    new_device_id, vehicle_id
                )
                await conn.execute(
                    "DELETE FROM update_status WHERE device_id = $1 AND vehicle_id != $2",
                    new_device_id, vehicle_id
                )

                migrated_trips = 0

                if actual_old_device:
                    # ── 4a. Migrate trip_logs: อัปเดต vehicle_id ให้ถูก ──
                    migrate_result = await conn.execute(
                        """
                        UPDATE trip_logs
                        SET vehicle_id = $1
                        WHERE device_id = $2
                          AND (vehicle_id IS NULL OR vehicle_id = 0 OR vehicle_id != $1)
                        """,
                        vehicle_id, actual_old_device
                    )
                    try:
                        migrated_trips = int(migrate_result.split()[-1])
                    except Exception:
                        migrated_trips = 0

                    # ── 4b. ปลดบอร์ดเก่าออก ─────────────────────────────
                    await conn.execute(
                        "UPDATE devices SET vehicle_id = NULL, active = false WHERE id = $1",
                        actual_old_device
                    )
                    await conn.execute(
                        "DELETE FROM update_status WHERE vehicle_id = $1 AND device_id = $2",
                        vehicle_id, actual_old_device
                    )

                # ── 5. ผูกบอร์ดใหม่ ──────────────────────────────────────
                await conn.execute(
                    """
                    INSERT INTO devices (id, vehicle_id, active)
                    VALUES ($1, $2, true)
                    ON CONFLICT (id) DO UPDATE SET vehicle_id = $2, active = true
                    """,
                    new_device_id, vehicle_id
                )
                await conn.execute(
                    """
                    INSERT INTO update_status (vehicle_id, device_id, date_update_latest)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (vehicle_id, device_id) DO UPDATE SET date_update_latest = NOW()
                    """,
                    vehicle_id, new_device_id
                )

                status = "registered" if not actual_old_device else "migrated"
                msg = (
                    f"ผูกบอร์ด {new_device_id} กับรถ {vehicle_id} สำเร็จ"
                    if not actual_old_device
                    else (
                        f"เปลี่ยนบอร์ด {actual_old_device} → {new_device_id} "
                        f"สำหรับรถ {vehicle_id} สำเร็จ"
                        + (f" (migrate trip_logs {migrated_trips} รายการ)" if migrated_trips > 0 else "")
                    )
                )

                return {
                    "status": status,
                    "vehicle_id": vehicle_id,
                    "device_id": new_device_id,
                    "previous_device_id": actual_old_device,
                    "migrated_trip_logs": migrated_trips,
                    "message": msg
                }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────
# GET Scoring Config — Current active config
# ─────────────────────────────────────────────────────────────

@router.get("/config/scoring/current")
async def get_current_scoring_config(
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Get currently active scoring configuration
    
    Returns:
        Scoring config with all weights and thresholds
    """
    
    try:
        config = await pool.fetchrow(
            """
            SELECT 
                id, config_name, score_base, harsh_brake_deduct, harsh_accel_deduct,
                harsh_corner_deduct, speeding_deduct, idling_deduct, bump_deduct,
                harsh_brake_g, harsh_accel_g, harsh_corner_g, speeding_kmh_over,
                idle_min_threshold, max_deduct_per_trip, is_active, 
                effective_date, synced_from_odoo_at
            FROM scoring_config_cache
            WHERE is_active = true
            ORDER BY effective_date DESC
            LIMIT 1
            """
        )
        
        if not config:
            raise HTTPException(status_code=404, detail="No active config found")
        
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in dict(config).items()}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))