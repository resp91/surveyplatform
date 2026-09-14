@echo off
chcp 65001 > nul
cd /d "%~dp0.."
REM 브라우저를 열지 않고 시나리오와 엑셀만 점검합니다.
python run.py run --dry-run --scenario config\scenario.yaml
pause
