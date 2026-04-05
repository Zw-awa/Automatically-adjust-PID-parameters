@echo off
echo ================================================
echo   PID Auto-Tuner - Online Mode
echo ================================================
echo.

set /p PORT="Enter serial port (e.g. COM3): "
set /p LOOP="Enter loop name (speed/steering/position/current): "
set /p INTERVAL="Enter tune interval in seconds (default 10): "

if "%INTERVAL%"=="" set INTERVAL=10

python main.py online --port %PORT% --loop %LOOP% --interval %INTERVAL%

echo.
pause
