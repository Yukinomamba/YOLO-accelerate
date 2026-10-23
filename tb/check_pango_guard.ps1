# Exercise the native job limit on small owned processes before running PDS.
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw 'Use a fresh probe output directory.' }
$null = New-Item -ItemType Directory -Path $out
$tokens = $null; $errors = $null
$null = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $repo 'tools\pango\run_synthesis.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
Add-Type -Path (Join-Path $repo 'tools\pango\GuardedJob.cs')
$probe = Join-Path $out 'guard_probe.exe'
Add-Type -OutputAssembly $probe -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Threading;
public class GuardProbe {
    public static int Main(string[] args) {
        if (args[0] == "normal") { Console.WriteLine("PASS normal"); return 0; }
        if (args[0] == "allocate") {
            try { byte[] data = new byte[128*1024*1024]; data[0] = 1; GC.KeepAlive(data); return 2; }
            catch (OutOfMemoryException) { Console.WriteLine("PASS allocation blocked"); return 0; }
        }
        if (args[0] == "tree") {
            ProcessStartInfo info = new ProcessStartInfo(typeof(GuardProbe).Assembly.Location, "wait");
            info.UseShellExecute = false;
            Process.Start(info);
        }
        Thread.Sleep(30000); return 0;
    }
}
'@
$results = @()
foreach ($mode in @('normal', 'allocate', 'tree')) {
    $log = Join-Path $out ($mode+'.log')
    $job = New-Object NpuGuardedJob($probe, $mode, $out, $log, [uint64](64MB))
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        if ($job.ConfiguredLimitBytes() -ne 64MB) { throw 'Hard memory limit readback mismatch.' }
        if ($mode -eq 'tree') {
            while ($job.ActiveProcesses() -lt 2 -and $timer.Elapsed.TotalSeconds -lt 5) { Start-Sleep -Milliseconds 20 }
            if ($job.ActiveProcesses() -lt 2) { throw 'Descendant did not inherit job membership.' }
            $job.Stop()
        }
        while ($job.ActiveProcesses() -and $timer.Elapsed.TotalSeconds -lt 8) { Start-Sleep -Milliseconds 20 }
        if ($job.ActiveProcesses()) { throw 'Probe timeout or descendant survived termination.' }
        $code = $job.ExitCode()
        if ($mode -eq 'tree') {
            if ($code -ne 124) { throw 'Unexpected termination code.' }
        } else {
            if ($code -ne 0 -or (Get-Content -Raw $log) -notmatch '^PASS ') { throw "Probe $mode failed: exit $code" }
        }
        $results += [ordered]@{mode=$mode; status='PASS'; exit_code=$code;
            configured_limit_bytes=$job.ConfiguredLimitBytes(); reported_peak_commit_bytes=$job.PeakCommitBytes()}
    } finally { $job.Dispose() }
}
[IO.File]::WriteAllText((Join-Path $out 'summary.json'), (($results | ConvertTo-Json)+[Environment]::NewLine))
Write-Output 'PASS native PDS guard: exit/log capture, 64 MiB allocation cap, descendant membership and termination.'
