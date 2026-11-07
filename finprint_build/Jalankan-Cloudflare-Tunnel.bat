@echo off
cd /d "%~dp0"
echo Pastikan FinPrint Pro dan Sync API sudah berjalan.
echo Jalankan cloudflared quick tunnel ke port 8765.
cloudflared tunnel --url http://localhost:8765
pause
