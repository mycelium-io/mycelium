; Mycelium's additions to Tauri's Windows installer.
;
; herdr stays up when the app quits, so the agents in it keep working, and an
; update can't overwrite what it and its panes have loaded: herdr.exe, its
; console host (conpty\) and any mycelium.exe an agent is running. Windows
; lets a running file be renamed, though, so before installing, every program
; and library in the install folder is moved aside as <name>.old. The install
; then writes fresh copies, what's running keeps its old ones until it next
; starts, and the app deletes the .old files once nothing holds them.

!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '$INSTDIR' -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $$_.Extension -in '.exe','.dll' } | ForEach-Object { Remove-Item -LiteralPath ($$_.FullName + '.old') -Force -ErrorAction SilentlyContinue; Rename-Item -LiteralPath $$_.FullName -NewName ($$_.Name + '.old') -ErrorAction SilentlyContinue }"`
  Pop $0
!macroend
