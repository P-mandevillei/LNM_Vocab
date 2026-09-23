@echo off
rem Double-click this file to start the Latin vocab quiz.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python server.py
pause
