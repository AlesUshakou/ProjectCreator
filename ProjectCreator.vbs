Set FSO = CreateObject("Scripting.FileSystemObject")
Set SH  = CreateObject("WScript.Shell")

base = FSO.GetParentFolderName(WScript.ScriptFullName) 'папка, где лежит VBS
SH.CurrentDirectory = base


SH.Run "pythonw.exe ""ProjectCreator.py""", 0, False
