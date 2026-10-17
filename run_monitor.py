import logging
from pathlib import Path
import time

from ydl_app_monitor.config import load_settings
from ydl_app_monitor.monitor import YdlMonitorService


Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/ydl_app_monitor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


def main() -> None:
    service = YdlMonitorService(load_settings())
    service.start()
    print("YDL app monitor started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()


if __name__ == "__main__":
    main()

