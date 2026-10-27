@echo off
chcp 65001 >nul
title Secretario por voz
cd /d "%~dp0"
".venv\Scripts\python.exe" assistente_voz.py
pause
