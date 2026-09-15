@echo off
rem الاسم تغيّر: هذا الملف صار keyboardless.cmd -- نُبقي هذا المُحوِّل حتى لا ينكسر أي اختصار قديم.
echo [!] الاسم الجديد هو keyboardless.cmd
call "%~dp0keyboardless.cmd" %*
