Option Explicit
Dim fso, shell, scriptDir, pythonw, scriptPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(scriptDir, ".venv\Scripts\pythonw.exe")
scriptPath = fso.BuildPath(scriptDir, "selecttrans.py")

If Not fso.FileExists(pythonw) Then
    MsgBox "Python environment not found. Please run setup.bat first.", 16, "SelectTrans"
    WScript.Quit 1
End If

shell.CurrentDirectory = scriptDir
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & scriptPath & Chr(34), 0, False
