@echo off
setlocal
cd /d "%~dp0"
python scripts\start_lab.py %*
