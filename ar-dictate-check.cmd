@echo off
rem الاسم تغيّر: هذا الملف صار keyboardless-check.cmd -- نُبقي هذا المُحوِّل حتى لا ينكسر أي اختصار قديم.
echo [!] الاسم الجديد هو keyboardless-check.cmd
call "%~dp0keyboardless-check.cmd" %*
