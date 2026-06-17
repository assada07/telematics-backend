# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database Settings (TimescaleDB)
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASS: str

    # MQTT Broker Settings
    MQTT_HOST: str
    MQTT_PORT: int
    MQTT_USER: str = "admin"   # ค่า Default ของ EMQX
    MQTT_PASS: str = "public"  # ค่า Default ของ EMQX
    MQTT_TOPIC: str

    # รหัสลับสำหรับตรวจสอบความถูกต้องข้อมูล (ต้องตรงกับฝั่ง ESP32)
    HMAC_SECRET: str = "fleet_hmac_secret_KTC001_2026"

    # โดดค่าจากไฟล์ .env โดยอัตโนมัติ
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()