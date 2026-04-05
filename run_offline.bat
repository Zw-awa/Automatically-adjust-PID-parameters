@echo off
echo ================================================
echo   PID Auto-Tuner - Offline Mode
echo ================================================
echo.

set /p FILE="Enter CSV data file path: "
set /p LOOP="Enter loop name (speed/steering/position/current): "

python main.py offline --file "%FILE%" --loop %LOOP%

echo.
pause
