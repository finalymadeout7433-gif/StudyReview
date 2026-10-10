$ErrorActionPreference='Stop'
$program=Join-Path $PSScriptRoot '..\Windows程序\StudyReview.exe'
Write-Host '仅新空库初始化：study_review_dev必须不存在，不覆盖已有库。'
Write-Host '本人先准备MySQL、已有localhost应用账户和程序外私有JSON。'
$dataChoice=Read-Host '数据目录完整路径（留空默认LOCALAPPDATA\StudyReview\data）'
if([string]::IsNullOrWhiteSpace($dataChoice)){$dataChoice=Join-Path $env:LOCALAPPDATA 'StudyReview\data'}
$credentialChoice=Read-Host '安全JSON完整路径，不输入或展示密码'
$demoChoice=Read-Host '本次新空库是否填入公开合成数据？输入Y选择'
$confirmationChoice=Read-Host '确认新建空库和向已有账户授四项DML，输入NEW-EMPTY执行'
if($confirmationChoice -cne 'NEW-EMPTY'){Write-Host '已取消，未连接。';exit 2}
$arguments=@('--initialize-new-empty-database','--confirm-existing-account-dml-grant','--data-dir',$dataChoice,'--credentials-file',$credentialChoice)
if($demoChoice -eq 'Y'){$arguments+='--seed-synthetic-demo'}
& $program @arguments
$resultCode=$LASTEXITCODE
if($resultCode -eq 0){Write-Host '完成，请点击启动拾习；演示账号见文档。'}
else{Write-Host '未完成，保留现场按说明检查，不删除已有库反复重试。'}
Read-Host '按回车关闭' | Out-Null
exit $resultCode
