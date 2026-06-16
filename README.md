# 🚗 Telematics Backend

Fleet Telematics API — FastAPI + TimescaleDB + EMQX + Redis

## โครงสร้างโฟลเดอร์

```
telematics-backend/
│
├── fleet-backend/              # FastAPI application
│   ├── app/
│   │   ├── api/                # REST API endpoints
│   │   │   ├── routes_vehicles.py    # GET /api/v1/vehicles/{id}/location
│   │   │   ├── routes_trips.py       # GET/POST /trips/scoring/config
│   │   │   ├── routes_drivers.py     # GET /drivers/{id}/bonus
│   │   │   └── routes_config.py      # config endpoints
│   │   ├── models/             # SQLAlchemy models
│   │   │   ├── telemetry.py    # TelemetryRaw, ScoringConfig
│   │   │   └── trip.py         # TripLog
│   │   ├── services/           # Business logic
│   │   │   ├── mqtt_subscriber.py    # รับข้อมูล GPS จาก EMQX
│   │   │   ├── trip_manager.py       # จัดการ trip lifecycle
│   │   │   ├── score_calculator.py   # คำนวณ driver score
│   │   │   └── event_processor.py    # ประมวลผล harsh events
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   └── main.py             # FastAPI app entry point
│   ├── tests/                  # pytest tests
│   │   └── test_api.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── docker/
│   └── nginx/
│       ├── nginx.conf          # nginx reverse proxy config
│       └── certs/              # SSL certificates
│
├── .github/
│   └── workflows/
│       ├── ci.yml              # CI: lint + test
│       ├── cd.yml              # CD: build + push image
│       └── deploy-local.yml    # Deploy บน self-hosted runner
│
├── docker-compose.yml          # Base: networks + volumes
├── docker-compose.backend.yml  # Backend services
├── docker-compose.dev.yml      # Development override
└── docker-compose.prod.yml     # Production override
```

## วิธีรัน

### Development
```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.backend.yml \
  -f docker-compose.dev.yml \
  up
```

### Production
```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.backend.yml \
  -f docker-compose.prod.yml \
  up -d
```

## GitHub Secrets ที่ต้องตั้งค่า

| Secret | คำอธิบาย |
|--------|---------|
| `POSTGRES_DB` | ชื่อ database |
| `POSTGRES_USER` | username |
| `POSTGRES_PASSWORD` | password |
| `EMQX_DASHBOARD_PASSWORD` | password หน้า dashboard EMQX |
| `SECRET_KEY` | JWT secret key |
| `ODOO_DB_NAME` | ชื่อ DB ของ Odoo |
| `ODOO_ADMIN_USER` | username Odoo admin |
| `ODOO_ADMIN_PASSWORD` | password Odoo admin |
# updated
