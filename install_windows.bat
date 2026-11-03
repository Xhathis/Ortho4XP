@echo off
echo Setting up Ortho4XP...
echo:

rem The bundled gdal and scikit-fmm wheels are built for Python 3.13 (cp313),
rem so use 3.13 through the py launcher even when a newer Python is the default.
set "PY=python"
py -3.13 -c "pass" >NUL 2>&1 && set "PY=py -3.13"
%PY% -c "import sys; sys.exit(sys.version_info[:2] != (3, 13))" >NUL 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.13 is required, the bundled wheels are built for it.
    echo Install it from python.org, or run: py install 3.13
    goto :fail
)

echo Setting up a Python virtual environment
%PY% -m venv venv || goto :fail
echo:

echo Activating the Python virtual environment
call venv\Scripts\activate.bat || goto :fail
echo:

echo Installing Python dependency: gdal
pip install Utils\win\gdal-3.12.2-cp313-cp313-win_amd64.whl || goto :fail
echo:

echo Installing Python dependency: scikit-fmm
pip install Utils\win\scikit_fmm-2025.6.23-cp313-cp313-win_amd64.whl || goto :fail
echo:

echo Installing remaining Python dependencies
pip install -r requirements.txt || goto :fail
echo:

echo Ortho4XP setup complete!
echo:

echo Use start_windows.bat to start Ortho4XP
echo:
goto :end

:fail
echo:
echo Ortho4XP setup FAILED, see the messages above.
echo:

:end
if defined VIRTUAL_ENV call deactivate
pause