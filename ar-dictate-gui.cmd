@echo off
rem الاسم تغيّر: هذا الملف صار keyboardless-gui.cmd -- نُبقي هذا المُحوِّل حتى لا ينكسر أي اختصار قديم.
echo [!] الاسم الجديد هو keyboardless-gui.cmd
call "%~dp0keyboardless-gui.cmd" %*
