@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python belum terpasang. Instal Python 3.10 atau lebih baru.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Menyiapkan FinPrint Pro pertama kali...
  python -m venv .venv
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call ".venv\Scripts\activate.bat"
  pip install -r requirements.txt
)
start "FinPrint Streamlit" /min cmd /c "python -m streamlit run app.py --server.headless true"
timeout /t 6 /nobreak >nul
start "FinPrint Sync API" /min cmd /c "python -m uvicorn api_server:app --host 0.0.0.0 --port 8765"
timeout /t 3 /nobreak >nul
start "" http://localhost:8501
echo FinPrint Pro PC dan Sync API sudah dijalankan.
echo Tes API: http://localhost:8765/api/health
pause
