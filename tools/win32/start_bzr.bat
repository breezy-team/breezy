@ECHO OFF

REM    ******************************************************
REM    **  You can change following environment variables  **
REM    **  that affects on bzr behaviour                   **
REM    ******************************************************

REM If you don't add Bzr directory to system-wide PATH environment variable
REM you can modify local PATH
REM SET PATH=C:\Program Files\Bazaar;%PATH%

REM Change next line to set-up e-mail to identify yourself in bzr
REM SET BZREMAIL=

REM Change next line to specify editor to edit commit messages
REM SET BZR_EDITOR=

REM Change next line to tell where bzr should search for plugins
REM SET BZR_PLUGIN_PATH=

REM Change next line to use another home directory with bzr
REM SET BZR_HOME=

REM Change next line to control verbosity of .bzr.log
REM SET BZR_DEBUG=30


REM --------------------------------------------------------------------------

bzr.exe help
@ECHO ON
