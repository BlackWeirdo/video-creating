; Inno Setup Script for Video Creator (Phase 08)
[Setup]
AppId={{C279BE7C-7B12-4A91-A8B8-13C763573B03}
AppName=Video Creator
AppVersion=0.1.0
AppPublisher=Internal Silver Jewelry Studio
DefaultDirName={localappdata}\Programs\VideoCreator
DefaultGroupName=Video Creator
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=VideoCreatorSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\installer\launch.vbs

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng trên màn hình Desktop"; GroupDescription: "Biểu tượng:"
Name: "startupicon"; Description: "Tự động chạy cùng Windows (dành cho máy chủ 24/7)"; GroupDescription: "Khởi động:"

[Files]
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "post_install.cmd"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "install_mpt.cmd"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "launch.vbs"; DestDir: "{app}\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\Video Creator"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"
Name: "{autodesktop}\Video Creator"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\Video Creator"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; Tasks: startupicon

[Run]
Filename: "{cmd}"; Parameters: "/c ""{app}\installer\post_install.cmd"""; WorkingDir: "{app}"; StatusMsg: "Đang thiết lập môi trường Python (uv sync)..."; Flags: runhidden waituntilterminated
Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"; Description: "Mở Video Creator ngay sau khi cài"; Flags: nowait postinstall skipifsilent
