import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import TypedDict

import cv2
import numpy as np


class Bounds(TypedDict):
    x: int
    y: int
    w: int
    h: int


class Contour(Bounds):
    area: float


def get_devices() -> list[str]:
    result = subprocess.run(
        ["adb", "devices"],
        capture_output=True,
        text=True,
        check=True,
    )

    devices = []

    for line in result.stdout.splitlines()[1:]:
        parts = line.split()

        if len(parts) == 2 and parts[1] == "device":
            devices.append(parts[0])

    return devices


def run_app(device: str, package: str) -> None:
    subprocess.run(
        ["adb", "-s", device, "shell", "monkey", "-p", package, "1"],
        check=True,
    )


def take_screenshot(device: str) -> bytes:
    result = subprocess.run(
        [
            "adb",
            "-s",
            device,
            "exec-out",
            "screencap",
            "-p",
        ],
        capture_output=True,
        check=True,
    )

    return result.stdout


def get_contours(image_bytes: bytes) -> list[Contour]:
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        sys.exit()

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    lower = (35, 40, 30)
    upper = (90, 255, 255)

    mask = cv2.inRange(hsv, lower, upper)

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    result = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)

        if area < 5000:
            continue

        result.append(Contour(x=x, y=y, w=w, h=h, area=area))

    # для дебага
    cv2.imwrite("mask.png", mask)

    return result


def get_clickable_elements(device: str) -> list[dict[str, str]]:
    subprocess.run(
        [
            "adb",
            "-s",
            device,
            "shell",
            "uiautomator",
            "dump",
            "/sdcard/window.xml",
        ],
        check=True,
        capture_output=True,
    )

    result = subprocess.run(
        [
            "adb",
            "-s",
            device,
            "shell",
            "cat",
            "/sdcard/window.xml",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    root = ET.fromstring(result.stdout)

    elements = []

    for node in root.iter("node"):
        attributes = node.attrib

        # ищу что-нибудь кликабельное
        if attributes.get("clickable") != "true":
            continue

        elements.append(
            {
                "text": attributes.get("text"),
                "class": attributes.get("class"),
                "bounds": attributes.get("bounds"),
            }
        )

    return elements


def parse_bounds(bounds: str) -> Bounds:
    values = [int(value) for value in re.findall(r"\d+", bounds)]
    x1, y1, x2, y2 = values
    return Bounds(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def intersects(first: Contour, second: Bounds) -> bool:
    first_x1 = first["x"]
    first_y1 = first["y"]
    first_x2 = first["x"] + first["w"]
    first_y2 = first["y"] + first["h"]

    second_x1 = second["x"]
    second_y1 = second["y"]
    second_x2 = second["x"] + second["w"]
    second_y2 = second["y"] + second["h"]

    return (
        first_x1 < second_x2
        and first_x2 > second_x1
        and first_y1 < second_y2
        and first_y2 > second_y1
    )


def click_element(device: str, bounds: Bounds) -> None:

    print("BOUNDS:", bounds)

    x = bounds["x"] + bounds["w"] // 2
    y = bounds["y"] + bounds["h"] // 2

    print(f"X{x}; Y{y}")

    subprocess.run(
        [
            "adb",
            "-s",
            device,
            "shell",
            "input",
            "tap",
            str(x),
            str(y),
        ],
        check=True,
    )


def relevant_match(
    contours: list[Contour],
    elements: list[dict[str, str]],
) -> Bounds | None:
    for green in contours:
        matches = []

        for element in elements:
            bounds = parse_bounds(element["bounds"])
            if intersects(green, bounds):
                matches.append(bounds)

        if matches:
            matches.sort(key=lambda bounds: bounds["w"] * bounds["h"])
            return matches[0]


if __name__ == "__main__":
    devices = get_devices()

    if len(devices) < 1:
        sys.exit("Девайс не найден")
    # беру первый попавшийся
    device = devices[0]

    if len(sys.argv) < 2:
        sys.exit("Введите имя пакета")
    package_name = sys.argv[1]

    run_app(device, package_name)

    # ожидаю открытия приложения
    time.sleep(2)

    raw_bytes = take_screenshot(device)
    contours = get_contours(raw_bytes)
    elements = get_clickable_elements(device)

    if not contours or not elements:
        sys.exit("Кнопка не найдена")

    match = relevant_match(contours, elements)

    if not match:
        sys.exit("Кнопка не найдена")
    click_element(device, match)
