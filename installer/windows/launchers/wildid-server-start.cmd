@echo off
rem Start the WildID server detached and windowless. The server exits by itself after its
rem idle timeout; stop it earlier from the plugin's server-status menu.
rem uv's venv pythonw.exe is a console-subsystem trampoline (uv 0.11), so a plain `start`
rem would leave a console window open for the server's lifetime: launch it with a hidden
rem window instead (the short flash of this script's own console is expected).
if not exist "%~dp0app\.venv\Scripts\pythonw.exe" (
  rem Environment not synced yet (installer ran offline?): sync first.
  "%~dp0uv.exe" sync --frozen --project "%~dp0app" || exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process -WindowStyle Hidden -FilePath \"%~dp0app\.venv\Scripts\pythonw.exe\" -ArgumentList '-m','wildid','serve'"
