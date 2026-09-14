@echo off
chcp 65001 > nul
cd /d "%~dp0.."
REM 실제로 브라우저를 띄워 자동 입력을 시작합니다.
REM 중간에 멈췄다면 아래 줄 끝에 --resume 을 붙여 이어서 실행하세요.
python run.py run --scenario config\scenario.yaml
pause
