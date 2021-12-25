@ECHO OFF

REM    ******************************************************
REM    **  You can change following environment variables  **
REM    **  that affects on brz behaviour                   **
REM    ******************************************************

REM Add the Brz directory to system-wide PATH environment variable
SET PATH=C:\Program Files\Breezy;%PATH%

REM Change next line to set-up e-mail to identify yourself in brz
REM SET BZREMAIL=

REM Change next line to specify editor to edit commit messages
REM SET BRZ_EDITOR=

REM Change next line to tell where brz should search for plugins
REM SET BRZ_PLUGIN_PATH=

REM Change next line to use another home directory with brz
REM SET BRZ_HOME=

REM Change next line to control verbosity of .brz.log
REM SET BRZ_DEBUG=30


REM --------------------------------------------------------------------------

@ECHO ON
@brz.exe help
