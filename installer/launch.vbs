Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
AppRoot = FSO.GetParentFolderName(FSO.GetParentFolderName(WScript.ScriptFullName))
WshShell.CurrentDirectory = AppRoot
PythonW = AppRoot & "\.venv\Scripts\pythonw.exe"
If FSO.FileExists(PythonW) Then
    WshShell.Run """" & PythonW & """ -m videocreator", 0, False
Else
    WshShell.Run """" & AppRoot & "\.venv\Scripts\python.exe"" -m videocreator", 0, False
End If
