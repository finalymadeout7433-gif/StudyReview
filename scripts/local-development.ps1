param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('start','stop','check','test')]
    [string]$Action,
    [Parameter(Mandatory=$true)][string]$DataDir,
    [Parameter(Mandatory=$true)][string]$CredentialsFile,
    [string]$PythonPath,
    [ValidateRange(1024,65535)][int]$Port=8001,
    [switch]$OpenBrowser
)

$ErrorActionPreference='Stop'
$OutputEncoding=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$OutputEncoding
$SourceRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$DataDir=[IO.Path]::GetFullPath($DataDir)
$CredentialsFile=[IO.Path]::GetFullPath($CredentialsFile)
if(-not $PythonPath){$PythonPath=Join-Path $SourceRoot '.venv\Scripts\python.exe'}
$PythonPath=[IO.Path]::GetFullPath($PythonPath)
foreach($required in @($PythonPath,$CredentialsFile,(Join-Path $DataDir 'private\development-environment.json'))){
    if(-not(Test-Path -LiteralPath $required -PathType Leaf)){throw 'Development environment is incomplete; see docs/13-local-development.md.'}
}
if($DataDir.StartsWith($SourceRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){
    throw 'Development data must be outside the Git checkout.'
}
$development=Get-Content -LiteralPath (Join-Path $DataDir 'private\development-environment.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if($development.database -notmatch '^study_review_v2_dev_[A-Za-z0-9_]+$' -or
   $development.test_database -notmatch '^test_study_review_v2_[A-Za-z0-9_]+$'){
    throw 'Only explicitly prepared isolated development and test schemas are allowed.'
}
$env:STUDY_DATA_DIR=$DataDir
$env:STUDY_CREDENTIALS_FILE=$CredentialsFile
$env:PYTHONIOENCODING='utf-8'
$env:STUDY_DEBUG='0'
$stateFile=Join-Path $DataDir 'private\desktop-state.json'

function Invoke-CheckedPython {
    param([string[]]$PythonArguments)
    & $PythonPath @PythonArguments
    if($LASTEXITCODE -ne 0){throw ('Python command failed with exit code '+$LASTEXITCODE+'.')}
}

function Test-DevelopmentHealth {
    if(-not(Test-Path -LiteralPath $stateFile)){return $false}
    try{
        $state=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if($state.port -ne $Port){throw 'Existing development process uses another port.'}
        $health=Invoke-RestMethod -Uri ('http://127.0.0.1:'+$Port+'/health/') -TimeoutSec 2
        return ($health.app -eq 'studyreview' -and $health.db -eq $true)
    }catch{return $false}
}

$previousLocation=Get-Location
try{
    Set-Location -LiteralPath $SourceRoot
    switch($Action){
        'start'{
            if(-not(Test-DevelopmentHealth)){
                if(Test-Path -LiteralPath $stateFile){
                    Invoke-CheckedPython -PythonArguments @('-m','desktop.development_state','--data-dir',$DataDir,'--port',"$Port")
                }
                $probe=New-Object Net.Sockets.TcpClient
                try{
                    $probe.Connect('127.0.0.1',$Port)
                    if($probe.Connected){throw 'Preview port is occupied. No process was stopped.'}
                }catch [Net.Sockets.SocketException]{}finally{$probe.Dispose()}
                Invoke-CheckedPython -PythonArguments @('manage.py','collectstatic','--settings=config.asset_build_settings','--noinput','--verbosity=0')
                $arguments='-m desktop.main --server-only --settings config.v2_development_settings --quiet --port '+$Port+
                    ' --data-dir "'+$DataDir+'" --credentials-file "'+$CredentialsFile+'"'
                $server=Start-Process -FilePath $PythonPath -ArgumentList $arguments -WorkingDirectory $SourceRoot -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput (Join-Path $DataDir 'private\development-server.stdout.log') `
                    -RedirectStandardError (Join-Path $DataDir 'private\development-server.stderr.log')
                $ready=$false
                for($attempt=0;$attempt -lt 100;$attempt++){
                    Start-Sleep -Milliseconds 250
                    if(Test-DevelopmentHealth){$ready=$true;break}
                    $server.Refresh()
                    if($server.HasExited){throw 'Development server exited; inspect its private stderr log.'}
                }
                if(-not $ready){throw 'Development startup timed out. Existing data was preserved.'}
            }
            $url='http://127.0.0.1:'+$Port+'/'
            Write-Host ('Development preview: '+$url)
            if($OpenBrowser){Start-Process $url | Out-Null}
        }
        'stop'{
            if(Test-Path -LiteralPath $stateFile){
                Invoke-CheckedPython -PythonArguments @('-m','desktop.main','--stop','--quiet','--data-dir',$DataDir)
                for($attempt=0;$attempt -lt 100;$attempt++){
                    if(-not(Test-Path -LiteralPath $stateFile)){break}
                    Start-Sleep -Milliseconds 250
                }
                if(Test-Path -LiteralPath $stateFile){throw 'Development server is still stopping. Its database was left running.'}
            }
            Write-Host 'Development preview stopped. No database was dropped.'
        }
        'check'{
            Invoke-CheckedPython -PythonArguments @('-m','pip','check')
            Invoke-CheckedPython -PythonArguments @('manage.py','check','--settings=config.v2_development_settings')
            Invoke-CheckedPython -PythonArguments @('manage.py','makemigrations','--check','--dry-run','--settings=config.v2_development_settings')
            Invoke-CheckedPython -PythonArguments @('scripts/verify_public_tree.py')
            & git diff --check
            if($LASTEXITCODE -ne 0){throw 'Git whitespace check failed.'}
        }
        'test'{
            $env:STUDY_ALLOW_SCHEMA_ADMIN='1'
            try{
                Invoke-CheckedPython -PythonArguments @('manage.py','test','learning','attachments','assistant','scheduling','ai_gateway',
                    '--settings=config.v2_integrated_test_settings','--keepdb','--noinput')
                Invoke-CheckedPython -PythonArguments @('-m','unittest','desktop.test_runtime','desktop.test_preflight',
                    'desktop.test_setup_wizard','desktop.test_initialization','desktop.test_bootstrap','desktop.test_development_state','-v')
            }finally{Remove-Item Env:STUDY_ALLOW_SCHEMA_ADMIN -ErrorAction SilentlyContinue}
        }
    }
}finally{Set-Location -LiteralPath $previousLocation}
