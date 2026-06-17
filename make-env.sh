#!/bin/bash
# สร้าง .env จาก GitHub Secrets
# รันก่อนเมื่อต้องการรันบนเครื่อง
gh secret list --repo assada07/telematics-backend

echo "กรุณาสร้าง .env เองจาก Secrets ด้านบนครับ"
