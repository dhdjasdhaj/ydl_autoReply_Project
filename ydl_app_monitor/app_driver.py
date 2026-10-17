import hashlib
import logging
import base64
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import Settings
from .models import UiNode, now_text


log = logging.getLogger(__name__)


Bounds = Tuple[int, int, int, int]


def parse_bounds(bounds: str) -> Optional[Bounds]:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def center_of(bounds: str) -> Optional[Tuple[int, int]]:
    parsed = parse_bounds(bounds)
    if not parsed:
        return None
    left, top, right, bottom = parsed
    return (left + right) // 2, (top + bottom) // 2


class YdlAppDriver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver: Any = None
        self._adb_started = False

    @property
    def started(self) -> bool:
        return self.driver is not None or self._adb_started

    @property
    def _using_adb_control(self) -> bool:
        return (self.settings.control_backend or "").strip().lower() == "adb"

    @property
    def supports_text_input(self) -> bool:
        return not self._using_adb_control

    def start(self) -> None:
        if self.started:
            return

        if self._using_adb_control:
            self._adb_activate_app()
            self._adb_started = True
            time.sleep(max(self.settings.app_startup_seconds, 1))
            return

        try:
            from appium import webdriver
            from appium.options.android import UiAutomator2Options
        except Exception as exc:
            raise RuntimeError(
                "Appium-Python-Client is not installed. Run: python -m pip install -r requirements.txt"
            ) from exc

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.device_name = self.settings.device_name
        options.no_reset = True
        options.new_command_timeout = self.settings.command_timeout_seconds
        if self.settings.device_udid:
            options.set_capability("appium:udid", self.settings.device_udid)

        if self.settings.app_activity:
            options.app_package = self.settings.app_package
            options.app_activity = self.settings.app_activity

        log.info("Connecting to Appium at %s", self.settings.appium_server_url)
        self.driver = webdriver.Remote(self.settings.appium_server_url, options=options)
        self.activate_app()

    def activate_app(self) -> None:
        if self._using_adb_control:
            self._adb_activate_app()
            time.sleep(max(self.settings.app_startup_seconds, 1))
            return

        self._require_driver()
        try:
            self.driver.activate_app(self.settings.app_package)
        except Exception:
            log.exception("activate_app failed; the Appium session will continue with the current app")
        time.sleep(max(self.settings.app_startup_seconds, 1))

    def stop(self) -> None:
        if self.driver is None:
            self._adb_started = False
            return
        try:
            self.driver.quit()
        finally:
            self.driver = None
            self._adb_started = False

    def page_source(self) -> str:
        self._require_started()
        backend = (self.settings.page_source_backend or "appium").strip().lower()
        if self._using_adb_control:
            return self._adb_page_source()
        if backend == "adb":
            return self._adb_page_source()
        if backend == "auto":
            try:
                return self.driver.page_source
            except Exception:
                log.exception("Appium page_source failed; falling back to adb uiautomator dump")
                return self._adb_page_source()
        return self.driver.page_source

    def nodes(self) -> List[UiNode]:
        source = self.page_source()
        try:
            root = ET.fromstring(source)
        except ET.ParseError:
            return []

        result: List[UiNode] = []
        for elem in root.iter():
            attr = elem.attrib
            text = (attr.get("text") or "").strip()
            desc = (attr.get("content-desc") or "").strip()
            hint = (attr.get("hint") or "").strip()
            resource_id = (attr.get("resource-id") or "").strip()
            class_name = (attr.get("class") or "").strip()
            bounds = (attr.get("bounds") or "").strip()
            if not any([text, desc, hint, resource_id, bounds]):
                continue
            result.append(UiNode(
                text=text,
                content_desc=desc,
                hint=hint,
                resource_id=resource_id,
                class_name=class_name,
                clickable=attr.get("clickable") == "true",
                enabled=attr.get("enabled", "true") == "true",
                bounds=bounds,
            ))
        return result

    def visible_texts(self, min_len: int = 1) -> List[str]:
        texts = []
        seen = set()
        for node in self.nodes():
            label = node.label
            if len(label) < min_len or label in seen:
                continue
            seen.add(label)
            texts.append(label)
        return texts

    def click_first_text(self, texts: Sequence[str], partial: bool = True) -> bool:
        node = self.find_node_by_text(texts, partial=partial, clickable_preferred=True)
        if node is None:
            return False
        return self.tap_node(node)

    def click_text_near_text(
        self,
        anchor_texts: Sequence[str],
        target_texts: Sequence[str],
        vertical_tolerance: int = 140,
        partial: bool = True,
    ) -> bool:
        nodes = self.nodes()
        anchors = [node for node in nodes if self._node_matches_texts(node, anchor_texts, partial)]
        targets = [node for node in nodes if self._node_matches_texts(node, target_texts, partial)]
        if not anchors or not targets:
            return False

        candidates = []
        for anchor in anchors:
            anchor_center = center_of(anchor.bounds)
            if anchor_center is None:
                continue
            for target in targets:
                target_center = center_of(target.bounds)
                if target_center is None:
                    continue
                vertical_delta = abs(target_center[1] - anchor_center[1])
                if vertical_delta > vertical_tolerance:
                    continue
                right_side_penalty = 0 if target_center[0] >= anchor_center[0] else 1000
                candidates.append((right_side_penalty + vertical_delta, target))

        if not candidates:
            return False
        candidates.sort(key=lambda item: item[0])
        return self.tap_node(candidates[0][1])

    def find_node_by_text(
        self,
        texts: Sequence[str],
        partial: bool = True,
        clickable_preferred: bool = False,
    ) -> Optional[UiNode]:
        candidates = []
        for node in self.nodes():
            label = node.label
            if not label or not node.bounds:
                continue
            for text in texts:
                if not text:
                    continue
                matched = text in label if partial else text == label
                if matched:
                    candidates.append(node)
                    break

        if not candidates:
            return None
        if clickable_preferred:
            clickable = [node for node in candidates if node.clickable]
            if clickable:
                return clickable[0]
        return candidates[0]

    def _node_matches_texts(self, node: UiNode, texts: Sequence[str], partial: bool) -> bool:
        label = node.label
        if not label or not node.bounds:
            return False
        for text in texts:
            if not text:
                continue
            if text in label if partial else text == label:
                return True
        return False

    def find_input(self, hints: Sequence[str]) -> Any:
        if self._using_adb_control:
            candidates = []
            for node in self.nodes():
                if node.class_name not in ("android.widget.EditText", "android.widget.AutoCompleteTextView"):
                    continue
                if not node.bounds:
                    continue
                candidates.append(node)
                label = f"{node.label} {node.resource_id}"
                if any(hint in label for hint in hints):
                    return node
            return candidates[-1] if candidates else None

        self._require_driver()
        try:
            from appium.webdriver.common.appiumby import AppiumBy
        except Exception as exc:
            raise RuntimeError("AppiumBy import failed. Check Appium-Python-Client installation.") from exc

        candidates = []
        for class_name in ("android.widget.EditText", "android.widget.AutoCompleteTextView"):
            try:
                candidates.extend(self.driver.find_elements(AppiumBy.CLASS_NAME, class_name))
            except Exception:
                continue

        for element in candidates:
            try:
                text = (element.text or "").strip()
                content_desc = (element.get_attribute("contentDescription") or "").strip()
                resource_id = (element.get_attribute("resourceId") or "").strip()
                label = f"{text} {content_desc} {resource_id}"
                if any(hint in label for hint in hints):
                    return element
            except Exception:
                continue

        return candidates[-1] if candidates else None

    def set_text(self, element: Any, text: str) -> None:
        if self._using_adb_control:
            if not isinstance(element, UiNode):
                raise RuntimeError("ADB text input requires a UiNode input element")
            self.tap_node(element)
            self._adb_clear_focused_text()
            self._adb_type_unicode(text)
            return

        self._require_driver()
        element.click()
        time.sleep(0.3)
        try:
            element.clear()
        except Exception:
            pass
        try:
            element.send_keys(text)
        except Exception:
            self.driver.set_clipboard_text(text)
            self.driver.press_keycode(279)

    def tap_node(self, node: UiNode) -> bool:
        center = center_of(node.bounds)
        if center is None:
            return False
        self.tap_xy(center[0], center[1])
        return True

    def tap_xy(self, x: int, y: int) -> None:
        self._require_started()
        if self._using_adb_control:
            self._adb_run(["shell", "input", "tap", str(x), str(y)], timeout=15)
            time.sleep(0.8)
            return

        try:
            self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
        except Exception:
            self.driver.tap([(x, y)], 120)
        time.sleep(0.8)

    def back(self) -> None:
        self._require_started()
        if self._using_adb_control:
            self._adb_run(["shell", "input", "keyevent", "4"], timeout=15)
            time.sleep(0.8)
            return

        self.driver.press_keycode(4)
        time.sleep(0.8)

    def clipboard_text(self) -> str:
        self._require_started()
        if self._using_adb_control:
            try:
                completed = self._adb_run(["shell", "cmd", "clipboard", "get"], timeout=15)
                return (completed.stdout or "").strip()
            except Exception:
                log.exception("Failed to read clipboard through adb")
                return ""

        self._require_driver()
        try:
            return (self.driver.get_clipboard_text() or "").strip()
        except Exception:
            log.exception("Failed to read clipboard through Appium")
            return ""

    def scroll_down(self, amount: float = 0.78) -> None:
        self._require_started()
        size = self._adb_window_size() if self._using_adb_control else self.driver.get_window_size()
        width = int(size.get("width", 1080))
        height = int(size.get("height", 1920))
        start_y = int(height * amount)
        end_y = int(height * 0.22)
        if self._using_adb_control:
            self._adb_run(
                ["shell", "input", "swipe", str(width // 2), str(start_y), str(width // 2), str(end_y), "700"],
                timeout=15,
            )
            time.sleep(1.1)
            return

        self.driver.swipe(width // 2, start_y, width // 2, end_y, 700)
        time.sleep(1.1)

    def dump(self, output_dir: Path, label: str = "page") -> Tuple[Path, Path]:
        self._require_started()
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_text().replace(":", "-").replace(" ", "_")
        safe_label = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
        xml_path = output_dir / f"{stamp}_{safe_label}.xml"
        png_path = output_dir / f"{stamp}_{safe_label}.png"
        xml_path.write_text(self.page_source(), encoding="utf-8")
        self.save_screenshot(png_path)
        return xml_path, png_path

    def save_screenshot(self, path: Path) -> None:
        self._require_started()
        if self._using_adb_control:
            self._adb_screencap(path)
            return

        try:
            self.driver.save_screenshot(str(path))
            return
        except Exception:
            log.exception("Appium screenshot failed; falling back to adb screencap")
        self._adb_screencap(path)

    def _adb_command_base(self) -> List[str]:
        command = [self.settings.adb_path or "adb"]
        if self.settings.device_udid:
            command.extend(["-s", self.settings.device_udid])
        return command

    def _adb_run(self, args: Sequence[str], timeout: int = 30) -> subprocess.CompletedProcess:
        command = self._adb_command_base() + list(args)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"adb command failed: {' '.join(command)}\n{completed.stderr.strip()}")
        return completed

    def _adb_activate_app(self) -> None:
        if self.settings.app_activity:
            component = f"{self.settings.app_package}/{self.settings.app_activity}"
            self._adb_run(["shell", "am", "start", "-n", component], timeout=30)
            return
        self._adb_run(
            ["shell", "monkey", "-p", self.settings.app_package, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=30,
        )

    def _adb_window_size(self) -> Dict[str, int]:
        completed = self._adb_run(["shell", "wm", "size"], timeout=15)
        match = re.search(r"(\d+)x(\d+)", completed.stdout or "")
        if not match:
            return {"width": 1080, "height": 1920}
        return {"width": int(match.group(1)), "height": int(match.group(2))}

    def _adb_type_unicode(self, text: str) -> None:
        if not text:
            return
        current_ime = self._adb_current_ime()
        try:
            self._adb_run(["shell", "ime", "enable", "io.appium.settings/.UnicodeIME"], timeout=15)
            self._adb_run(["shell", "ime", "set", "io.appium.settings/.UnicodeIME"], timeout=15)
            for chunk in self._chunks(text, 60):
                encoded = self._imap_utf7_encode(chunk)
                self._adb_run(["shell", "input", "text", self._remote_shell_single_quote(encoded)], timeout=30)
        finally:
            if current_ime:
                try:
                    self._adb_run(["shell", "ime", "set", current_ime], timeout=15)
                except Exception:
                    log.exception("Failed to restore input method: %s", current_ime)

    def _adb_clear_focused_text(self, max_chars: int = 600) -> None:
        self._adb_run(["shell", "input", "keyevent", "123"], timeout=15)
        keycodes = ["67"] * max_chars
        for index in range(0, len(keycodes), 100):
            self._adb_run(["shell", "input", "keyevent", *keycodes[index:index + 100]], timeout=30)

    def _adb_current_ime(self) -> str:
        completed = self._adb_run(["shell", "settings", "get", "secure", "default_input_method"], timeout=15)
        value = (completed.stdout or "").strip()
        return "" if value == "null" else value

    def _imap_utf7_encode(self, text: str) -> str:
        def encode_chunk(match: re.Match) -> str:
            chunk = match.group(0)
            payload = base64.b64encode(chunk.encode("utf-16-be")).decode("ascii").rstrip("=")
            return f"&{payload.replace('/', ',')}-"

        return re.sub(r"[^\x20-\x7e]+", encode_chunk, text.replace("&", "&-"))

    def _remote_shell_single_quote(self, text: str) -> str:
        return "'" + text.replace("'", "'\\''") + "'"

    def _chunks(self, text: str, size: int) -> Iterable[str]:
        for index in range(0, len(text), size):
            yield text[index:index + size]

    def _adb_page_source(self) -> str:
        command = self._adb_command_base() + ["exec-out", "uiautomator", "dump", "/dev/tty"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"adb uiautomator dump failed: {completed.stderr.strip()}")

        output = completed.stdout or ""
        start = output.find("<?xml")
        end = output.rfind("</hierarchy>")
        if start < 0 or end < 0:
            sample = (output or completed.stderr or "").strip().replace("\r", "\\r").replace("\n", "\\n")[:500]
            raise RuntimeError(f"adb uiautomator dump did not return XML hierarchy: {sample}")
        return output[start:end + len("</hierarchy>")]

    def _adb_screencap(self, path: Path) -> None:
        command = self._adb_command_base() + ["exec-out", "screencap", "-p"]
        with path.open("wb") as file:
            completed = subprocess.run(
                command,
                stdout=file,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        if completed.returncode != 0:
            error = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"adb screencap failed: {error}")

    def _require_driver(self) -> None:
        if self.driver is None:
            raise RuntimeError("Appium driver is not started")

    def _require_started(self) -> None:
        if not self.started:
            raise RuntimeError("App driver is not started")


def stable_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:20]
