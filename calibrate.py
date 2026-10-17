import sys

from ydl_app_monitor.config import load_settings
from ydl_app_monitor.app_driver import YdlAppDriver


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = load_settings()
    app = YdlAppDriver(settings)
    try:
        app.start()
        paths = app.dump(settings.dumps_dir, "manual_calibration")
        print(f"XML: {paths[0]}")
        print(f"Screenshot: {paths[1]}")
        print("Visible texts:")
        for text in app.visible_texts(min_len=1)[:200]:
            print(f"- {text}")
    finally:
        app.stop()


if __name__ == "__main__":
    main()
