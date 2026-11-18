Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
AppRoot = FSO.GetParentFolderName(FSO.GetParentFolderName(WScript.ScriptFullName))
WshShell.CurrentDirectory = AppRoot
PythonW = AppRoot & "\.venv\Scripts\pythonw.exe"
PythonExe = AppRoot & "\.venv\Scripts\python.exe"

If Not FSO.FileExists(PythonW) And Not FSO.FileExists(PythonExe) Then
    PostInstall = AppRoot & "\installer\post_install.cmd"
    If FSO.FileExists(PostInstall) Then
        WshShell.Run "cmd.exe /c """"" & PostInstall & """""", 1, True
    End If
End If

If FSO.FileExists(PythonW) Then
    WshShell.Run """" & PythonW & """ -m videocreator", 0, False
ElseIf FSO.FileExists(PythonExe) Then
    WshShell.Run """" & PythonExe & """ -m videocreator", 0, False
Else
    MsgBox "Chua tim thay moi truong Python (.venv) tai:" & vbCrLf & AppRoot & vbCrLf & vbCrLf & "Hay chay file installer\post_install.cmd de cai dat thu vien.", 16, "Video Creator"
End If
