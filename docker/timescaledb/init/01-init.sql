CREATE USER fleet_user WITH PASSWORD 'telematics1234';
CREATE DATABASE fleet_db OWNER fleet_user;
GRANT ALL PRIVILEGES ON DATABASE fleet_db TO fleet_user;
