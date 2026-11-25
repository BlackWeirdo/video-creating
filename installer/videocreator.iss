; Inno Setup Script for Video Creator V2 Offline Desktop Installer (Stage R6)
#define MyAppVersion "2.1.0"

[Setup]
AppId={{C279BE7C-7B12-4A91-A8B8-13C763573B03}
AppName=Video Creator V2
AppVersion={#MyAppVersion}
AppPublisher=Video Creator V2 Studio
DefaultDirName={localappdata}\Programs\VideoCreatorV2
DefaultGroupName=Video Creator V2
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=VideoCreatorV2Setup
SetupIconFile=videocreator.ico
UninstallDisplayIcon={app}\installer\videocreator.ico
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng Video Creator V2 ngoài màn hình Desktop"; GroupDescription: "Biểu tượng:"
Name: "startupicon"; Description: "Tự động chạy cùng Windows (dành cho Kênh Autopilot 24/7)"; GroupDescription: "Khởi động:"; Flags: unchecked

[Files]
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\web-next\.next\standalone\*"; DestDir: "{app}\web-next\.next\standalone"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "post_install.cmd"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "post_install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "launch.vbs"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "videocreator.ico"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "stage_bundle.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\runtime\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\runtime\node\*"; DestDir: "{app}\runtime\node"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\runtime\ffmpeg\*"; DestDir: "{app}\runtime\ffmpeg"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\runtime\yt-dlp\*"; DestDir: "{app}\runtime\yt-dlp"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\runtime\uv\*"; DestDir: "{app}\runtime\uv"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "staging\runtime_sha256.json"; DestDir: "{app}\runtime"; Flags: ignoreversion
Source: "staging\venv\*"; DestDir: "{app}\.venv"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\freecut\*"; DestDir: "{app}\tools\freecut"; Flags: ignoreversion recursesubdirs createallsubdirs
#if DirExists("..\build\nuitka")
Source: "..\build\nuitka\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\Video Creator V2"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\installer\videocreator.ico"
Name: "{autodesktop}\Video Creator V2"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\installer\videocreator.ico"; Tasks: desktopicon
Name: "{userstartup}\Video Creator V2"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\installer\videocreator.ico"; Tasks: startupicon

[Run]
Filename: "{cmd}"; Parameters: "/c ""{app}\installer\post_install.cmd"""; WorkingDir: "{app}"; StatusMsg: "Đang kích hoạt môi trường Python 3.11 & AI Offline..."; Flags: waituntilterminated runhidden
Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; Description: "Mở Video Creator V2 ngay sau khi cài"; Flags: nowait postinstall skipifsilent
