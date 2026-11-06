"""Apply an OS-enforced ceiling before a parser receives untrusted bytes."""

import os


def limit_process_memory(megabytes: int):
    """Return the Windows job handle (keep alive); Linux uses RLIMIT_AS."""
    size = megabytes * 1024 * 1024
    if os.name == "posix":
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = size if hard == resource.RLIM_INFINITY else min(size, hard)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
        return None
    if os.name != "nt":
        raise RuntimeError("Parser memory isolation is unsupported on this operating system")
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                    ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                    ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcesses", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("Basic", BasicLimits), ("IO", IO), ("ProcessMemory", ctypes.c_size_t),
                    ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t), ("PeakJob", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.Basic.Flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.ProcessMemory = size
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        if job:
            kernel.CloseHandle(job)
        raise RuntimeError("Cannot configure parser memory isolation")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise RuntimeError("Cannot activate parser memory isolation")
    return job
