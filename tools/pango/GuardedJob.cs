// Own-process Windows Job Object: children inherit a hard combined commit limit.
// The root starts suspended so no PDS child can escape assignment. No breakaway flag.
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public sealed class NpuGuardedJob : IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters {
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [StructLayout(LayoutKind.Sequential)] struct Accounting {
        public long UserTime, KernelTime, PeriodUserTime, PeriodKernelTime;
        public uint PageFaults, TotalProcesses, ActiveProcesses, TerminatedProcesses;
    }
    [StructLayout(LayoutKind.Sequential)] struct Security {
        public uint Length;
        public IntPtr Descriptor;
        public int Inherit;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public uint Size;
        public string Reserved, Desktop, Title;
        public uint X, Y, XSize, YSize, XChars, YChars, Fill, Flags;
        public ushort Show, ReservedSize;
        public IntPtr ReservedPointer, Input, Output, Error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo {
        public IntPtr Process, Thread;
        public uint Pid, Tid;
    }
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits value, uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int kind, out ExtendedLimits value, uint size, IntPtr length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int kind, out Accounting value, uint size, IntPtr length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr CreateFile(string path, uint access, uint share, ref Security security, uint disposition, uint attributes, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool CreateProcess(string executable, StringBuilder command, IntPtr processAttrs, IntPtr threadAttrs, bool inheritHandles, uint flags, IntPtr environment, string directory, ref Startup startup, out ProcessInfo info);
    IntPtr job, process;
    public uint RootPid { get; private set; }

    static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }
    static bool Valid(IntPtr handle) { return handle != IntPtr.Zero && handle != new IntPtr(-1); }

    public NpuGuardedJob(string executable, string arguments, string directory, string log, ulong limit) {
        IntPtr output = IntPtr.Zero, input = IntPtr.Zero, thread = IntPtr.Zero;
        try {
            job = CreateJobObject(IntPtr.Zero, null);
            Check(Valid(job));
            ExtendedLimits limits = new ExtendedLimits();
            limits.Basic.Flags = 0x200 | 0x2000; // JOB_MEMORY | KILL_ON_JOB_CLOSE
            limits.JobMemory = new UIntPtr(limit);
            Check(SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits)));
            Security attrs = new Security(); attrs.Length = (uint)Marshal.SizeOf(attrs); attrs.Inherit = 1;
            output = CreateFile(log, 0x40000000, 1, ref attrs, 1, 0x80, IntPtr.Zero); // CREATE_NEW
            Check(Valid(output));
            input = CreateFile("NUL", 0x80000000, 3, ref attrs, 3, 0x80, IntPtr.Zero);
            Check(Valid(input));
            Startup startup = new Startup(); startup.Size = (uint)Marshal.SizeOf(startup);
            startup.Flags = 0x100; startup.Input = input; startup.Output = output; startup.Error = output;
            ProcessInfo pi;
            Check(CreateProcess(executable, new StringBuilder("\""+executable+"\" "+arguments),
                IntPtr.Zero, IntPtr.Zero, true, 0x4 | 0x4000 | 0x08000000,
                IntPtr.Zero, directory, ref startup, out pi)); // SUSPENDED | BELOW_NORMAL | NO_WINDOW
            process = pi.Process; thread = pi.Thread; RootPid = pi.Pid;
            Check(AssignProcessToJobObject(job, process));
            Check(ResumeThread(thread) != 0xffffffff);
        } catch {
            // Even assignment failure only terminates the root just created by this instance.
            if (Valid(process)) TerminateProcess(process, 125);
            Dispose();
            throw;
        } finally {
            if (Valid(thread)) CloseHandle(thread);
            if (Valid(input)) CloseHandle(input);
            if (Valid(output)) CloseHandle(output);
        }
    }
    public uint ActiveProcesses() {
        Accounting value;
        Check(QueryInformationJobObject(job, 1, out value, (uint)Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero));
        return value.ActiveProcesses;
    }
    public ulong PeakCommitBytes() {
        ExtendedLimits value;
        Check(QueryInformationJobObject(job, 9, out value, (uint)Marshal.SizeOf(typeof(ExtendedLimits)), IntPtr.Zero));
        return value.PeakJobMemory.ToUInt64();
    }
    public ulong ConfiguredLimitBytes() {
        ExtendedLimits value;
        Check(QueryInformationJobObject(job, 9, out value, (uint)Marshal.SizeOf(typeof(ExtendedLimits)), IntPtr.Zero));
        if ((value.Basic.Flags & 0x2200) != 0x2200) throw new InvalidOperationException("Job limit flags lost");
        return value.JobMemory.ToUInt64();
    }
    public uint ExitCode() { uint code; Check(GetExitCodeProcess(process, out code)); return code; }
    public void Stop() { if (Valid(job)) Check(TerminateJobObject(job, 124)); }
    public void Dispose() {
        if (Valid(job)) { CloseHandle(job); job = IntPtr.Zero; }
        if (Valid(process)) { CloseHandle(process); process = IntPtr.Zero; }
    }
}
