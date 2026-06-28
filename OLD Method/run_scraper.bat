@echo off
set PYTHONUTF8=1
cd /d "D:\Mac Drive\Python Project\Python Clients\Jason LaFrance\usef-horse-rankings"
set LOGFILE=logs\run_%date:~-4%-%date:~4,2%-%date:~7,2%.log
if not exist logs mkdir logs
"D:\Mac Drive\Python Project\.venv\Scripts\python.exe" run.py >> %LOGFILE% 2>&1