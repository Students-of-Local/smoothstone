import ctypes
import sys
import threading

import pytest


@pytest.mark.skipif(not sys.platform.startswith("linux") or not hasattr(ctypes.CDLL(None), "malloc_info"), reason="glibc only")
def test_a_worker_keeps_few_malloc_arenas_however_many_threads_run(tmp_path):
    """An arena per thread kept 1.1 GB in a worker, and four such workers ran the suite out of memory."""
    libc = ctypes.CDLL(None)
    libc.malloc.restype = libc.fopen.restype = ctypes.c_void_p
    libc.free.argtypes = libc.fclose.argtypes = [ctypes.c_void_p]
    libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
    all_in = threading.Barrier(16)

    def work():
        all_in.wait()
        held = [libc.malloc(1000) for _ in range(200)]
        all_in.wait()
        for p in held:
            libc.free(p)

    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = libc.fopen(str(tmp_path / "info.xml").encode(), b"w")
    libc.malloc_info(0, out)
    libc.fclose(out)
    assert 1 <= (tmp_path / "info.xml").read_text().count("<heap nr=") <= 4
