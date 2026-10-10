param([switch]$Quiet)
$ErrorActionPreference='Stop'
$program=Join-Path $PSScriptRoot '..\Windows程序\StudyReview.exe'
$arguments=@('--setup','--prefer-saved-data','--data-dir',(Join-Path $env:LOCALAPPDATA 'StudyReview\data'))
if($Quiet){$arguments+='--quiet'}
& $program @arguments
exit $LASTEXITCODE
