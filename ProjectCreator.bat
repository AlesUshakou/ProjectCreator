@echo off
title Project Creator Runner
echo === Running ProjectCreator.py ===
echo.

:: Запуск основного скрипта
python ProjectCreator.py
if %errorlevel% neq 0 (
    echo.
    echo === Python error detected! Installing requirements... ===
    echo.
    python -m pip install -r requirements.txt
    echo.
    echo === Retrying script... ===
    echo.
    python ProjectCreator.py
)

echo.
echo === Done! ===
pause