# mock_hardware_stream.py
import json
import hmac
import hashlib
import time
import asyncio
from paho.mqtt import client as mqtt_client

# ในไฟล์ mock_hardware_stream.py (ปรับแต่งท่อนบนประมาณบรรทัดที่ 9-11)
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "kotchasaan/fleet/KTC-001/telemetry"
#แปะรหัสผ่านลับจริงที่พี่เจอลงไปตรงนี้
HMAC_SECRET = "fleet_hmac_secret_KTC001_2026"

def generate_signed_payload(data: dict, secret_key: str) -> str:
    """ฟังก์ชันแปลง JSON และฝังลายเซ็น HMAC-SHA256 ลงในข้อความตามรูปแบบฮาร์ดแวร์จริง"""
    payload_str = json.dumps(data, separators=(',', ':'))
    # ตัดปีกกาปิดออกเพื่อแปะฟิลด์ลายเซ็นต์เข้าไปต่อท้าย
    base_str = payload_str[:-1]
    
    # คำนวณหาค่าแฮช
    sig = hmac.new(
        secret_key.encode('utf-8'),
        payload_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # ประกอบฟิลด์ "sig" กลับเข้าไปในข้อความ JSON ตัวเต็ม
    final_signed_str = f'{base_str},"sig":"{sig}"}}'
    return final_signed_str

async def main():
    print("🚀 เริ่มระบบจำลองการสตรีมข้อมูลจากกล่อง GPS (KTC-Test)...")
    
    # ต่อสายเข้าหา MQTT Broker ใน Docker Local ของพี่
    client = mqtt_client.Client(callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    # 🕒 จำลองเวลาปัจจุบัน (ใช้วินาที Epoch)
    base_ts = int(time.time())

    # 🎬 ฉากการทดสอบที่ 1: บิดกุญแจสตาร์ทรถยนต์ (Ignition = True)
    # เพื่อกระตุ้นให้ mqtt_subscriber.py สั่ง "เริ่มนับทริปใหม่ (Trip Start)"
    print("\n🎬 [Event 1/4] สตาร์ทรถยนต์เพื่อเปิดทริปการเดินทาง...")
    start_payload = {
        "ts": base_ts, "device_id": "KTC-001", "lat": 13.7563, "lon": 100.5018,
        "speed": 0.0, "heading": 90, "alt": 10, "hdop": 0.9, "rpm": 850,
        "throttle": 0.0, "engine_load": 15.0, "coolant_temp": 85, "fuel_level": 80.0,
        "maf": 4.5, "ax": 0.0, "ay": 0.0, "az": 1.0, "gx": 0.0, "gy": 0.0, "gz": 0.0,
        "event": "", "event_severity": 0.0, "ignition": True, "temperature": 25.5, "humidity": 60.0
    }
    client.publish(MQTT_TOPIC, generate_signed_payload(start_payload, HMAC_SECRET))
    await asyncio.sleep(2)

    # 🚨 ฉากการทดสอบที่ 2: วิ่งเร็วเกินกำหนดกลางดึก (Overspeeding ตอนตี 2)
    # เพื่อเช็กว่าตรรกะ Circadian Danger Zone สามารถเพิ่มตัวคูณการตัดแต้มจาก 5 คะแนนเป็น 7.5 คะแนนได้ไหม
    print("🚨 [Event 2/4] วิ่งความเร็ว 110 กม./ชม. เกินเกณฑ์ช่วงเวลากลางคืนอันตราย (ตี 2)...")
    # แอบหลอกเวลาวัตถุในระบบให้เป็นช่วงเวลาตี 2 (ชั่วโมงที่ 2 ของวัน)
    midnight_ts = int(time.strptime(f"{time.strftime('%Y-%m-%d')} 02:30:00", "%Y-%m-%d %H:%M:%S").tm_sec)
    overspeed_payload = start_payload.copy()
    overspeed_payload.update({"ts": base_ts + 10, "speed": 110.0, "rpm": 3200})
    client.publish(MQTT_TOPIC, generate_signed_payload(overspeed_payload, HMAC_SECRET))
    await asyncio.sleep(2)

    # 🚧 ฉากการทดสอบที่ 3: เกิดเหตุเบรกกะทันหันในเขตก่อสร้าง (Harsh Braking + Exemption)
    # เพื่อเช็กระบบเว้นคะแนนไดนามิก ถ้ารถวิ่งช้ากว่า 20 กม./ชม. คะแนนต้อง "ไม่ถูกหัก"
    print("🚧 [Event 3/4] เบรกกะทันหันอย่างรุนแรงในเขตก่อสร้าง (ความเร็วต่ำ 15 กม./ชม.)...")
    braking_payload = start_payload.copy()
    braking_payload.update({
        "ts": base_ts + 20, "speed": 15.0, "harsh_braking": True, 
        "event": "harsh_brake", "event_severity": 2.5, "ax": -0.65
    })
    client.publish(MQTT_TOPIC, generate_signed_payload(braking_payload, HMAC_SECRET))
    await asyncio.sleep(2)

    # 🏁 ฉากการทดสอบที่ 4: ขี่ถึงที่หมายแล้วทำการดับเครื่องยนต์ (Ignition = False)
    # เพื่อกระตุ้นระบบรวบรวมทริป "ปิดทริปคิดแต้มสรุป (Trip End)" บันทึกลงฐานข้อมูลและเตรียมส่ง Odoo
    print("🏁 [Event 4/4] ดับเครื่องยนต์ ปิดทริปการเดินทางและประมวลผลสรุปคะแนน...")
    stop_payload = start_payload.copy()
    stop_payload.update({"ts": base_ts + 30, "speed": 0.0, "rpm": 0, "ignition": False})
    client.publish(MQTT_TOPIC, generate_signed_payload(stop_payload, HMAC_SECRET))
    
    await asyncio.sleep(3)
    client.loop_stop()
    client.disconnect()
    print("\n✅ ยิงสตรีมข้อมูลทดสอบเสร็จสมบูรณ์!")

if __name__ == "__main__":
    asyncio.run(main())