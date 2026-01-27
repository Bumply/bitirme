@echo off
REM ========================================================
REM Transfer Project to Raspberry Pi via SCP
REM ========================================================

echo.
echo ================================================
echo   TRANSFER PROJECT TO RASPBERRY PI
echo ================================================
echo.

REM Check if pscp is available (from PuTTY)
where pscp >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: pscp not found!
    echo.
    echo Please install PuTTY which includes pscp:
    echo https://www.putty.org/
    echo.
    echo Alternatively, you can use a USB drive to transfer files.
    echo.
    pause
    exit /b 1
)

REM Get Raspberry Pi IP address
set /p PI_IP="Enter Raspberry Pi IP address (e.g., 192.168.1.100): "

REM Get username (default: pi)
set /p PI_USER="Enter Raspberry Pi username [default: pi]: "
if "%PI_USER%"=="" set PI_USER=pi

echo.
echo Transferring files to %PI_USER%@%PI_IP%...
echo This may take a few minutes...
echo.

REM Transfer the entire project folder
pscp -r "%~dp0" %PI_USER%@%PI_IP%:~/face-pose-main

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ================================================
    echo   TRANSFER COMPLETE!
    echo ================================================
    echo.
    echo Next steps:
    echo   1. SSH into your Raspberry Pi:
    echo      ssh %PI_USER%@%PI_IP%
    echo.
    echo   2. Run the setup script:
    echo      cd ~/face-pose-main
    echo      chmod +x setup.sh
    echo      bash setup.sh
    echo.
    echo   3. Wait for setup to complete (1-2 hours)
    echo.
    echo   4. Reboot when prompted
    echo.
) else (
    echo.
    echo ERROR: Transfer failed!
    echo.
    echo Please check:
    echo   - Raspberry Pi is powered on
    echo   - IP address is correct
    echo   - SSH is enabled on Raspberry Pi
    echo   - Network connection is working
    echo.
)

pause
