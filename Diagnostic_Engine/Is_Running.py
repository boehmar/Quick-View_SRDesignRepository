import os

import psutil

def is_running(proc_pid):
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['pid'] == proc_pid:
            return proc.name()
    return False

