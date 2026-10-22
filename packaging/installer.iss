; Instalador de OptiWin (Inno Setup 6). Se compila desde packaging/build.py:
;   ISCC /DAppVersion=0.5.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7B1E9F3A-52C4-4D86-9E0B-3A6C41D8F2B7}
AppName=OptiWin
AppVersion={#AppVersion}
AppVerName=OptiWin {#AppVersion}
AppPublisher=IJustDaniii
AppPublisherURL=https://github.com/IJustDaniii/optimizacion
AppSupportURL=https://github.com/IJustDaniii/optimizacion/issues
DefaultDirName={autopf}\OptiWin
DefaultGroupName=OptiWin
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\OptiWin.exe
UninstallDisplayName=OptiWin
SetupIconFile=..\src\optiwin\assets\optiwin.ico
OutputDir=..\dist
OutputBaseFilename=OptiWin-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Instalación por usuario (sin UAC) para que las actualizaciones sean silenciosas; se puede elegir "para todos".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "..\dist\OptiWin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OptiWin"; Filename: "{app}\OptiWin.exe"
Name: "{autodesktop}\OptiWin"; Filename: "{app}\OptiWin.exe"; Tasks: desktopicon

[Registry]
; Si el usuario activó "Iniciar con Windows", se quita al desinstalar.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "OptiWin"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\OptiWin.exe"; Description: "Abrir OptiWin"; Flags: nowait postinstall skipifsilent
; Tras una actualización silenciosa (la lanza la propia app) se vuelve a abrir.
Filename: "{app}\OptiWin.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
; Al desinstalar se devuelven a su valor original todos los ajustes que OptiWin había cambiado.
Filename: "{app}\optiwin-cli.exe"; Parameters: "revert-all"; Flags: runhidden skipifdoesntexist; RunOnceId: "RevertAll"
