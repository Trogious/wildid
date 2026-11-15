@echo off
rem WildID CLI launcher: runs wildid from the uv-managed project environment.
rem --frozen keeps the env exactly on uv.lock; a healthy env needs no network.
"%~dp0uv.exe" run --frozen --project "%~dp0app" wildid %*
