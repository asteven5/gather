"""Roku discovery and casting via ECP (External Control Protocol)."""

import socket
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from config import logger

_SSDP_ADDR = "239.255.255.250"
_SSDP_PORT = 1900
_ROKU_ECP_PORT = 8060
_SSDP_REQUEST = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"Host: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
    'Man: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: roku:ecp\r\n"
    "\r\n"
)


def get_local_ip() -> str:
    """Return this machine's LAN IP so Roku can reach our server."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


def _parse_device_info(location: str) -> dict | None:
    """Fetch the Roku device-info XML and return a friendly dict."""
    try:
        base = location.rstrip("/")
        res = requests.get(f"{base}/query/device-info", timeout=3)
        res.raise_for_status()
        root = ET.fromstring(res.text)

        name = root.findtext("user-device-name") or root.findtext("friendly-device-name") or "Roku"
        model = root.findtext("model-name") or "Unknown"
        ip = base.replace("http://", "").split(":")[0]

        return {"name": name.strip(), "model": model.strip(), "ip": ip}
    except Exception as exc:
        logger.warning("Failed to query Roku at %s: %s", location, exc)
        return None


def discover_roku_devices(timeout: float = 3.0) -> list[dict]:
    """Scan the local network for Roku devices via SSDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    try:
        sock.sendto(_SSDP_REQUEST.encode(), (_SSDP_ADDR, _SSDP_PORT))
    except OSError as exc:
        logger.warning("SSDP send failed: %s", exc)
        sock.close()
        return []

    locations: set[str] = set()
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            for line in data.decode(errors="ignore").splitlines():
                if line.upper().startswith("LOCATION:"):
                    locations.add(line.split(":", 1)[1].strip())
        except socket.timeout:
            break

    sock.close()

    devices: list[dict] = []
    seen_ips: set[str] = set()
    for loc in locations:
        info = _parse_device_info(loc)
        if info and info["ip"] not in seen_ips:
            seen_ips.add(info["ip"])
            devices.append(info)

    logger.info("Discovered %d Roku device(s)", len(devices))
    return devices


def cast_to_roku(roku_ip: str, video_url: str, title: str = "Gather") -> bool:
    """Launch a video on a Roku device via ECP.

    Uses the Roku Media Player (channel 15985) which is built into every Roku.
    """
    params = urllib.parse.urlencode({
        "t": "v",
        "u": video_url,
        "k": "(null)",
        "videoName": title,
        "videoFormat": "mp4",
    })
    url = f"http://{roku_ip}:{_ROKU_ECP_PORT}/launch/15985?{params}"

    try:
        res = requests.post(url, timeout=5)
        if res.status_code in (200, 204):
            logger.info("Cast to %s succeeded", roku_ip)
            return True
        logger.warning("Roku returned %d: %s", res.status_code, res.text)
        return False
    except Exception as exc:
        logger.error("Failed to cast to %s: %s", roku_ip, exc)
        return False
