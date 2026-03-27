@echo off
:: NewSong Updater - pulls latest code from GitHub, preserves config.py

set DEST=C:\Tools\NewSong
set TEMP_CONFIG=%TEMP%\newsong_config_backup.py

:: Backup config.py
if exist "%DEST%\config.py" (
    copy /y "%DEST%\config.py" "%TEMP_CONFIG%" >nul
    echo Backed up config.py
)

:: Pull latest from GitHub
cd /d "%DEST%"
git pull origin main

:: Restore config.py (git pull must not overwrite credentials)
if exist "%TEMP_CONFIG%" (
    copy /y "%TEMP_CONFIG%" "%DEST%\config.py" >nul
    del "%TEMP_CONFIG%" >nul
    echo Restored config.py
) else (
    echo WARNING: No config backup found - check config.py credentials
)

echo.
echo Done. Run your command again.
