@echo off
rem Double-click, or run `run` from a terminal in this folder.
rem   run --parents 2 --watches 2      two parents, two watches, one dashboard
python "%~dp0run.py" %*
rem 7 means the console's Shut down button did this on purpose, so close the
rem window with everything else. Anything else stays open so the reason can be
rem read. Only ever closes the window this script opened.
if errorlevel 7 exit
pause
