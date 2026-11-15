@echo off
rem First-run wizard: model download (a Hugging Face token is optional), offline verification.
"%~dp0uv.exe" run --frozen --project "%~dp0app" wildid setup
echo.
pause
