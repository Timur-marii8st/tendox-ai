#Requires -Version 5.1

[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$PostgresPort = 55432,

    [ValidateSet("Docker", "Local")]
    [string]$Backend = "Docker",

    [string]$PostgresBin = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$projectName = "vibe-seller-postgres-gate-$PID"
$databaseName = "procurement_gate"
$ownerRole = "procurement_owner"
$runtimeRole = "procurement_app"
$postgresTests = @(
    "tests/integration/test_postgres_gate.py",
    "tests/integration/test_storage.py",
    "tests/integration/test_document_storage.py",
    "tests/integration/test_ai_transfer_raw_sql.py",
    "tests/integration/test_ai_transfer_materialization_sql.py",
    "tests/integration/test_case_evidence_binding_sql.py",
    "tests/integration/test_case_from_evidence_sql.py",
    "tests/integration/test_reviewed_requirement_set_sql.py",
    "tests/integration/test_api_postgres.py"
)
$managedVariables = @(
    "APP_DB_PASSWORD",
    "COMPOSE_PROJECT_NAME",
    "DATABASE_ADMIN_URL",
    "DATABASE_URL",
    "PGPASSWORD",
    "POSTGRES_EXPECTED_MAJOR",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "POSTGRES_USER"
)
$previousEnvironment = @{}
$composeStarted = $false
$localClusterStarted = $false
$localClusterRoot = $null
$localDataDirectory = $null
$localPgCtl = $null

foreach ($name in $managedVariables) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

function Resolve-PostgresBin {
    if ($PostgresBin) {
        return [IO.Path]::GetFullPath($PostgresBin)
    }

    $initdbCommand = Get-Command initdb -ErrorAction SilentlyContinue
    if ($initdbCommand) {
        return Split-Path -Parent $initdbCommand.Source
    }

    $candidates = @()
    foreach ($programFilesRoot in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $programFilesRoot) {
            continue
        }
        $postgresRoot = Join-Path $programFilesRoot "PostgreSQL"
        if (-not (Test-Path -LiteralPath $postgresRoot -PathType Container)) {
            continue
        }
        $candidates += Get-ChildItem -LiteralPath $postgresRoot -Directory |
            ForEach-Object { Join-Path $_.FullName "bin" } |
            Where-Object { Test-Path -LiteralPath (Join-Path $_ "initdb.exe") -PathType Leaf }
    }

    $selected = $candidates | Sort-Object -Descending | Select-Object -First 1
    if (-not $selected) {
        throw "Local backend requires PostgreSQL 16+ binaries or -PostgresBin."
    }
    return $selected
}

function Initialize-LocalPostgres {
    $bin = Resolve-PostgresBin
    $requiredExecutables = @("createdb.exe", "initdb.exe", "pg_ctl.exe", "psql.exe")
    foreach ($executableName in $requiredExecutables) {
        $path = Join-Path $bin $executableName
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Local PostgreSQL executable is missing: $path"
        }
    }

    $postgres = Join-Path $bin "postgres.exe"
    $versionText = & $postgres --version
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch "PostgreSQL\)\s+(\d+)") {
        throw "Could not determine local PostgreSQL version from '$postgres'."
    }
    if ([int]$Matches[1] -lt 16) {
        throw "Local PostgreSQL 16+ is required; found: $versionText"
    }
    $env:POSTGRES_EXPECTED_MAJOR = $Matches[1]

    $script:localClusterRoot = Join-Path (
        [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    ) ("vibe-seller-postgres-gate-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
    $script:localDataDirectory = Join-Path $script:localClusterRoot "data"
    $ownerPasswordFile = Join-Path $script:localClusterRoot "owner-password.txt"
    $postgresLog = Join-Path $script:localClusterRoot "postgres.log"
    [IO.Directory]::CreateDirectory($script:localClusterRoot) | Out-Null
    [IO.File]::WriteAllText($ownerPasswordFile, $env:POSTGRES_PASSWORD)

    $initdb = Join-Path $bin "initdb.exe"
    $script:localPgCtl = Join-Path $bin "pg_ctl.exe"
    $createdb = Join-Path $bin "createdb.exe"
    $psql = Join-Path $bin "psql.exe"

    Write-Host "Initializing isolated $versionText cluster on port $PostgresPort."
    Invoke-Checked $initdb `
        --pgdata $script:localDataDirectory `
        --username $ownerRole `
        --pwfile $ownerPasswordFile `
        --auth-local trust `
        --auth-host scram-sha-256 `
        --encoding UTF8 `
        --no-locale

    $serverOptions = "-h 127.0.0.1 -p $PostgresPort"
    Invoke-Checked $script:localPgCtl `
        --pgdata $script:localDataDirectory `
        --log $postgresLog `
        --options $serverOptions `
        --wait `
        start
    $script:localClusterStarted = $true

    $env:PGPASSWORD = $env:POSTGRES_PASSWORD
    Invoke-Checked $createdb `
        --host 127.0.0.1 `
        --port $PostgresPort `
        --username $ownerRole `
        $databaseName

    $roleSql = @"
CREATE ROLE $runtimeRole LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    PASSWORD '$($env:APP_DB_PASSWORD)';
GRANT CONNECT ON DATABASE $databaseName TO $runtimeRole;
GRANT USAGE ON SCHEMA public TO $runtimeRole;
"@
    $roleSql | & $psql `
        --host 127.0.0.1 `
        --port $PostgresPort `
        --username $ownerRole `
        --dbname $databaseName `
        --set ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the local PostgreSQL runtime role."
    }
    [IO.File]::Delete($ownerPasswordFile)
    Write-Host "Local PostgreSQL cluster is ready."
}

try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required for the PostgreSQL verification gate"
    }

    $env:POSTGRES_DB = $databaseName
    $env:POSTGRES_USER = $ownerRole
    $env:POSTGRES_PASSWORD = [Guid]::NewGuid().ToString("N")
    $env:APP_DB_PASSWORD = [Guid]::NewGuid().ToString("N")
    $env:POSTGRES_PORT = $PostgresPort.ToString()
    $env:DATABASE_ADMIN_URL = (
        "postgresql+psycopg://{0}:{1}@127.0.0.1:{2}/{3}" -f
        $ownerRole,
        $env:POSTGRES_PASSWORD,
        $env:POSTGRES_PORT,
        $databaseName
    )
    $env:DATABASE_URL = (
        "postgresql+psycopg://{0}:{1}@127.0.0.1:{2}/{3}" -f
        $runtimeRole,
        $env:APP_DB_PASSWORD,
        $env:POSTGRES_PORT,
        $databaseName
    )

    Push-Location $repositoryRoot
    try {
        if ($Backend -eq "Docker") {
            if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
                throw "Docker backend requires the docker CLI."
            }
            Invoke-Checked docker version --format "{{.Server.Version}}"
            Invoke-Checked docker compose version
            $env:COMPOSE_PROJECT_NAME = $projectName
            $env:POSTGRES_EXPECTED_MAJOR = "16"

            Write-Host "Starting isolated PostgreSQL 16 project '$projectName' on port $PostgresPort."
            $composeStarted = $true
            Invoke-Checked docker compose --project-name $projectName up -d --wait postgres
        }
        else {
            Initialize-LocalPostgres
        }

        Write-Host "Applying all migrations to a fresh database."
        Invoke-Checked uv run alembic upgrade head

        Write-Host "Running the mandatory PostgreSQL integration gate."
        $pytestArguments = @("run", "pytest") + $postgresTests + @(
            "--require-postgres",
            "-q",
            "-rs",
            "--tb=short"
        )
        Invoke-Checked uv @pytestArguments
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($composeStarted) {
        Push-Location $repositoryRoot
        try {
            Write-Host "Removing isolated PostgreSQL gate containers and volume."
            & docker compose --project-name $projectName down --volumes --remove-orphans
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Cleanup failed for Compose project '$projectName'."
            }
        }
        finally {
            Pop-Location
        }
    }

    if ($localClusterStarted -and $localPgCtl -and $localDataDirectory) {
        Write-Host "Stopping isolated local PostgreSQL cluster."
        & $localPgCtl --pgdata $localDataDirectory --mode fast --wait stop
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Cleanup failed to stop local PostgreSQL."
        }
    }
    if ($localClusterRoot -and (Test-Path -LiteralPath $localClusterRoot)) {
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        $resolvedClusterRoot = [IO.Path]::GetFullPath($localClusterRoot)
        $expectedPrefix = Join-Path $tempRoot "vibe-seller-postgres-gate-"
        if (-not $resolvedClusterRoot.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected local PostgreSQL path: $resolvedClusterRoot"
        }
        [IO.Directory]::Delete($resolvedClusterRoot, $true)
    }

    foreach ($name in $managedVariables) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}
