param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Start')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$postgresRoot = Join-Path $root '.local/postgresql'
$pgCtl = Join-Path $postgresRoot 'pgsql/bin/pg_ctl.exe'
$data = Join-Path $postgresRoot 'data'
if (!(Test-Path -LiteralPath $pgCtl) -or !(Test-Path -LiteralPath (Join-Path $data 'PG_VERSION'))) {
    throw 'Local PostgreSQL is not initialized. See README database setup.'
}
switch ($Action) {
    'Start' {
        & $pgCtl -D $data status *> $null
        if ($LASTEXITCODE -eq 0) { Write-Output 'Local PostgreSQL is already running.'; exit 0 }
        $arguments = @('-D', ('"' + $data + '"'), '-l', ('"' + (Join-Path $postgresRoot 'server.log') + '"'), '-o', '"-h 127.0.0.1 -p 5432"', '-w', 'start')
        $process = Start-Process -FilePath $pgCtl -ArgumentList $arguments -WindowStyle Hidden -PassThru
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw 'PostgreSQL did not start; check .local/postgresql/server.log.' }
        Write-Output 'Local PostgreSQL is running on 127.0.0.1:5432.'
    }
    'Stop' { & $pgCtl -D $data -m fast -w stop; if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL stop failed.' } }
    'Status' { & $pgCtl -D $data status; exit $LASTEXITCODE }
}
