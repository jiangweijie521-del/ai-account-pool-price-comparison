@echo off
setlocal

where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0server.py" --open
if errorlevel 1 pause
goto end

:use_python
where python >nul 2>nul
if errorlevel 1 goto missing
python "%~dp0server.py" --open
if errorlevel 1 pause
goto end

:missing
echo Python 3 was not found.
echo Install Python 3 and try again.
pause

:end
endlocal
