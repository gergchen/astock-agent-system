@echo off
cd /d "C:\Users\Administrator\AppData\Local\Temp\Douyin_TikTok_Download_API"
echo Starting Douyin API on http://localhost:8000 ...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
