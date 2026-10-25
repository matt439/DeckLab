@echo off
rem Start Deck Lab's background server from any folder.
rem   decklab            starts it (same as "decklab start")
rem   decklab stop|restart|status|...   passes through to python -m decklab.lib.homenet
setlocal
pushd "%~dp0.." || exit /b 1
if "%~1"=="" (
    python -m decklab.lib.homenet start
) else (
    python -m decklab.lib.homenet %*
)
set "rc=%ERRORLEVEL%"
popd
exit /b %rc%
