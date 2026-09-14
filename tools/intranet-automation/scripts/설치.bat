@echo off
chcp 65001 > nul
cd /d "%~dp0.."
echo [1/3] 파이썬 확인
python --version || (echo 파이썬이 없습니다. https://www.python.org 에서 3.10 이상을 설치하세요. & pause & exit /b 1)
echo [2/3] 필요한 패키지 설치
python -m pip install -r requirements.txt || (pause & exit /b 1)
echo [3/3] 자동화용 브라우저 설치
python -m playwright install chromium || (pause & exit /b 1)
echo.
echo 설치가 끝났습니다. config\.env.example 을 config\.env 로 복사해 아이디와 비밀번호를 넣으세요.
pause
