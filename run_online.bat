@echo off
echo ================================================
echo   Automatically-adjust-PID-parameters - Online Mode
echo ================================================
echo.

set /p PORT="Enter serial port (default example COM3, change to your actual port): "
set /p LOOP="Enter loop name (speed/steering/position/current): "
set /p INTERVAL="Enter tune interval in seconds (default 10): "

if "%INTERVAL%"=="" set INTERVAL=10

python main.py online --port %PORT% --loop %LOOP% --interval %INTERVAL%

echo.
pause
