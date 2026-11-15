; WildID per-user installer (Inno Setup 6). Build with installer/windows/build.ps1,
; which stages payload\ (uv.exe + the locked project + the Lightroom plugin) first.
; Unsigned (plan L14); signing is a phase-P concern.

#define MyAppName "WildID"
#ifndef MyAppVersion
  #define MyAppVersion "0.2.0"
#endif

[Setup]
AppId={{8C1D4A77-3C2B-4F6E-9A64-2D5B7E1F0C21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=wildid
DefaultDirName={localappdata}\Programs\WildID
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=output
OutputBaseFilename=WildID-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Inno Setup 6.7+ enables Windows' RedirectionGuard on Setup and its [Run] children inherit it:
; they then cannot follow NTFS junctions created by a non-elevated user, and uv's managed
; Python alias directory (%APPDATA%\uv\python\cpython-3.14-windows-x86_64-none) is exactly
; that, so `uv sync` failed with "untrusted mount point" (os error 448) on Windows 11 25H2.
; This is a per-user installer writing only into the user's own profile; the hardening buys
; nothing here. Revisit if the installer ever needs elevation.
RedirectionGuard=no

[Files]
Source: "payload\uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "launchers\wildid.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "launchers\wildid-setup.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "launchers\wildid-server-start.cmd"; DestDir: "{app}"; Flags: ignoreversion
; Lightroom Classic auto-loads plugins from the per-user Modules folder: no Plug-in Manager step.
Source: "payload\wildid.lrplugin\*"; DestDir: "{userappdata}\Adobe\Lightroom\Modules\wildid.lrplugin"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\WildID\WildID Setup"; Filename: "{app}\wildid-setup.cmd"; WorkingDir: "{app}"
Name: "{userprograms}\WildID\WildID Server"; Filename: "{app}\wildid-server-start.cmd"; WorkingDir: "{app}"

[Run]
; Resolve the locked Python environment (uv also provisions the pinned Python itself).
; PyTorch is several GB: needs the network; progress shows in the console window.
Filename: "{app}\uv.exe"; Parameters: "sync --frozen --project ""{app}\app"""; \
  StatusMsg: "Installing the Python environment (several GB, needs the network)..."; \
  Flags: waituntilterminated
Filename: "{app}\wildid-setup.cmd"; Description: "Run the WildID setup wizard now (model download and offline check)"; \
  Flags: postinstall nowait

[UninstallDelete]
; The env and compiled caches live under {app}; model + geo caches survive on purpose
; (%LOCALAPPDATA%\wildid and the Hugging Face cache) so a reinstall needs no re-download.
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{userappdata}\Adobe\Lightroom\Modules\wildid.lrplugin"

[Code]
function JsonPath(const S: String): String;
var
  T: String;
begin
  T := S;
  StringChangeEx(T, '\', '\\', True);
  Result := T;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PluginDir, Content: String;
begin
  if CurStep = ssPostInstall then
  begin
    { engine.json tells the Lightroom plugin where the engine and its cache live. }
    PluginDir := ExpandConstant('{userappdata}\Adobe\Lightroom\Modules\wildid.lrplugin');
    Content := '{' + #13#10
      + '  "start": "' + JsonPath(ExpandConstant('{app}\wildid-server-start.cmd')) + '",' + #13#10
      + '  "cli": "' + JsonPath(ExpandConstant('{app}\wildid.cmd')) + '",' + #13#10
      + '  "cacheDir": "' + JsonPath(ExpandConstant('{localappdata}\wildid\Cache')) + '"' + #13#10
      + '}' + #13#10;
    if not SaveStringToFile(PluginDir + '\engine.json', Content, False) then
      Log('WildID: could not write engine.json into ' + PluginDir);
  end;
end;
