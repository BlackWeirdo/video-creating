Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
AppRoot = FSO.GetParentFolderName(FSO.GetParentFolderName(WScript.ScriptFullName))
WshShell.CurrentDirectory = AppRoot

PyHome = AppRoot & "\runtime\python"
NodeBin = AppRoot & "\runtime\node\node.exe"
FfmpegDir = AppRoot & "\runtime\ffmpeg"
YtDlpBin = AppRoot & "\runtime\yt-dlp\yt-dlp.exe"
UvBin = AppRoot & "\runtime\uv\uv.exe"
VenvCfg = AppRoot & "\.venv\pyvenv.cfg"
PythonW = AppRoot & "\.venv\Scripts\pythonw.exe"
PythonExe = AppRoot & "\.venv\Scripts\python.exe"

' Relocate prebuilt offline .venv to current AppRoot\runtime\python without any network calls
If FSO.FolderExists(AppRoot & "\.venv") And FSO.FileExists(PyHome & "\python.exe") Then
    Set CfgStream = FSO.CreateTextFile(VenvCfg, True, False)
    CfgStream.WriteLine "home = " & PyHome
    CfgStream.WriteLine "implementation = CPython"
    CfgStream.WriteLine "version_info = 3.11.18"
    CfgStream.WriteLine "include-system-site-packages = false"
    CfgStream.WriteLine "prompt = videocreator-v2"
    CfgStream.Close
End If

Set ProcEnv = WshShell.Environment("PROCESS")
If FSO.FileExists(NodeBin) Then
    ProcEnv("VIDEOCREATOR_NODE_BIN") = NodeBin
End If
If FSO.FolderExists(FfmpegDir) Then
    ProcEnv("VIDEOCREATOR_FFMPEG_DIR") = FfmpegDir
End If
If FSO.FileExists(YtDlpBin) Then
    ProcEnv("VIDEOCREATOR_YTDLP_BIN") = YtDlpBin
End If
If FSO.FileExists(UvBin) Then
    ProcEnv("VIDEOCREATOR_UV_BIN") = UvBin
End If
If FSO.FileExists(PythonExe) Then
    ProcEnv("VIDEOCREATOR_PYTHON_BIN") = PythonExe
End If
ProcEnv("VIDEOCREATOR_APP_ROOT") = AppRoot
ProcEnv("PYTHONPATH") = AppRoot & "\src"

BundledPath = FfmpegDir & ";" & AppRoot & "\runtime\node;" & AppRoot & "\runtime\yt-dlp;" & AppRoot & "\runtime\uv;" & PyHome
ExistingPath = ProcEnv("PATH")
If Len(ExistingPath) > 0 Then
    ProcEnv("PATH") = BundledPath & ";" & ExistingPath
Else
    ProcEnv("PATH") = BundledPath
End If

If FSO.FileExists(PythonW) Then
    WshShell.Run """" & PythonW & """ -m videocreator", 0, False
ElseIf FSO.FileExists(PythonExe) Then
    WshShell.Run """" & PythonExe & """ -m videocreator", 0, False
Else
    MsgBox "Khong tim thay moi truong Python dong goi (.venv) tai:" & vbCrLf & AppRoot & vbCrLf & vbCrLf & "Vui long chay lai bo cai VideoCreatorV2Setup.exe.", 16, "Video Creator V2"
End If
