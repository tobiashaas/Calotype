@echo off
title Calotype Bridge
cd /d "%~dp0"
echo ============================================================
echo           CALOTYPE BRIDGE - LIGHTROOM CLASSIC AI
echo ============================================================
echo.
echo Initialisiere lokale GPU-Engine (NVIDIA CUDA)...
echo Bridge API: http://127.0.0.1:47600
echo.
echo Du kannst jetzt in Lightroom Classic arbeiten:
echo   Bibliothek -^> Zusatzmodul-Optionen -^> Profil auf ausgewaehlte Fotos anwenden...
echo.
.venv\Scripts\python.exe tools\calotype_bridge_server.py
pause
