@echo off
rem Double-click, or run `run` from a terminal in this folder.
rem   run --parents 2 --watches 2      two parents, two watches, one dashboard
python "%~dp0run.py" %*
pause
