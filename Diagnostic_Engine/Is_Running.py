# import os
# import psutil

#def is_running(proc_name):
#    for proc in psutil.process_iter(['pid', 'name']):
#        if proc.info['name'] == proc_name:
#            return proc.name()
#    return False




#def is_running(proc_pid):
#    for proc in psutil.process_iter(['pid', 'name']):
#        if psutil.pid_exists(proc_pid):
#            return proc.name()
#    return False

"""
Windows: list installed apps, then show which ones are running (with PIDs).
Requires:  pip install psutil
"""

import os
import winreg
import psutil

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def get_installed_apps():
    """Return {app name: install folder (or None)} from the registry."""
    apps = {}
    for hive, path in UNINSTALL_KEYS:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                sub = winreg.OpenKey(root, winreg.EnumKey(root, i))
                name = winreg.QueryValueEx(sub, "DisplayName")[0]
            except OSError:
                continue
            try:
                folder = winreg.QueryValueEx(sub, "InstallLocation")[0]
            except OSError:
                folder = None
            folder = os.path.normcase(folder.strip('" ')) if folder else None
            apps[name.strip()] = folder
    return apps


def main():
    apps = get_installed_apps()

    print(f"=== Installed apps ({len(apps)}) ===")
    for name in sorted(apps, key=str.lower):
        print(f"  {name}")

    # For each running process, find the installed app whose folder contains its .exe
    running = {}  # app name -> list of PIDs
    for proc in psutil.process_iter(["pid", "exe"]):
        exe = proc.info["exe"]
        if not exe:
            continue
        exe = os.path.normcase(exe)
        for name, folder in apps.items():
            if folder and exe.startswith(folder.rstrip("\\") + "\\"):
                running.setdefault(name, []).append(proc.info["pid"])
                break

    print(f"\n=== Running apps ({len(running)}) ===")
    for name in sorted(running, key=str.lower):
        print(f"  {name}  (PIDs: {', '.join(map(str, running[name]))})")


if __name__ == "__main__":
    main()

