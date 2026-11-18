import os
import sys
import threading
from backend import app
import webview


def get_file_path(filename):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.abspath("."), filename)


def run_flask():
    app.run(port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    html_path = get_file_path("index.html")
    webview.create_window(
        "QuickView - Service & Network Monitor",
        f"file://{html_path}",
        width=950,
        height=750,
    )
    webview.start()