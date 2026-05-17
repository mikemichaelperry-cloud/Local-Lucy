#!/usr/bin/env python3
"""Simple resource monitor that logs GPU and RAM to a file every 5s."""
import subprocess, sys, time
from datetime import datetime
from pathlib import Path

log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/lucy_resource_monitor.log")

def sample():
    gpu = None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            parts = out.stdout.strip().split(",")
            gpu = {"used": int(parts[0].strip()), "total": int(parts[1].strip()), "util": int(parts[2].strip())}
    except Exception:
        pass
    ram_used = ram_total = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    ram_total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    ram_used = ram_total - int(line.split()[1]) // 1024
    except Exception:
        pass
    return gpu, ram_used, ram_total

print(f"Monitoring → {log_path}")
with open(log_path, "w") as f:
    f.write("timestamp,gpu_used,gpu_total,gpu_util,ram_used,ram_total\n")
    while True:
        gpu, ram_used, ram_total = sample()
        ts = datetime.now().isoformat()
        f.write(f"{ts},{gpu['used'] if gpu else ''},{gpu['total'] if gpu else ''},{gpu['util'] if gpu else ''},{ram_used},{ram_total}\n")
        f.flush()
        time.sleep(5)
