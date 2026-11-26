#!/usr/bin/env python3
"""Full-page screenshots of every screen at the three facelift widths.

    .venv/bin/python scripts/shots.py before            # -> docs/facelift/shots/before/
    .venv/bin/python scripts/shots.py after --base http://127.0.0.1:8421

Drives a headless Chrome over its DevTools socket with nothing but the
standard library, so it adds no dependency. Beside each picture it records
what a picture cannot show at a glance: whether the page scrolls sideways and
which elements have text cut off inside them. That lands in `report.json`.

A development tool for the facelift branch; the app never imports it.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTHS = {390: 844, 1280: 800, 1920: 1080}

#: name -> path. Ids are whatever the notebook copy in ./data happens to hold;
#: override with --pages a JSON file of the same shape.
PAGES = {
    "home": "/",
    "jar-detail": "/jars/2",
    "jar-new": "/jars/new",
    "jar-edit": "/jars/2/edit",
    "jar-feed": "/jars/2/feed",
    "jar-observe": "/jars/2/observe",
    "recipes": "/recipes",
    "recipe-version": "/recipes/35",
    "recipe-new": "/recipes/new",
    "recipe-edit": "/recipes/35/edit",
    "recipe-diff": "/recipes/35/diff",
    "bakes": "/bakes",
    "bake-new": "/bakes/new",
    "bake-running": "/bakes/7",
    "bake-done": "/bakes/6",
    "bake-result": "/bakes/6/result",
    "plan": "/plan",
    "equipment": "/equipment",
    "settings": "/settings",
    "backup": "/backup",
    "about": "/about",
    "photos-compare": "/photos/compare",
}

#: Runs in the page. Sideways scroll, and elements whose own text is clipped.
PROBE = r"""
(() => {
  const doc = document.documentElement;
  const vw = doc.clientWidth;
  const clipped = [];
  const spill = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const label = el.tagName.toLowerCase() +
      (el.className && el.className.baseVal === undefined && el.className
        ? '.' + String(el.className).trim().split(/\s+/).join('.') : '');
    if (r.right > vw + 1 && !el.closest('svg')) {
      let scroller = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX;
        if (o === 'auto' || o === 'scroll' || o === 'hidden') { scroller = true; break; }
      }
      if (!scroller) spill.push(label + ' +' + Math.round(r.right - vw));
    }
    if (el.scrollWidth > el.clientWidth + 1 && el.childElementCount === 0 &&
        (cs.overflowX === 'hidden' || cs.textOverflow === 'ellipsis')) {
      clipped.push(label + ': ' + el.textContent.trim().slice(0, 40));
    }
  }
  const scrollers = [...document.querySelectorAll('body *')].filter(el => {
    const o = getComputedStyle(el).overflowX;
    return (o === 'auto' || o === 'scroll') && el.scrollWidth > el.clientWidth + 1;
  }).map(el => el.tagName.toLowerCase() + '.' + String(el.className).split(/\s+/).join('.') +
              ' ' + el.scrollWidth + '>' + el.clientWidth);
  return JSON.stringify({
    height: Math.ceil(doc.scrollHeight),
    pageScrollsSideways: doc.scrollWidth > vw + 1,
    spill: spill.slice(0, 12), clipped: clipped.slice(0, 12),
    sidewaysScrollers: scrollers.slice(0, 12),
  });
})()
"""


class Socket:
    """Just enough of RFC 6455 to talk to DevTools."""

    def __init__(self, url: str) -> None:
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise ConnectionError("devtools socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, text: str) -> None:
        data = text.encode()
        mask = os.urandom(4)
        head = b"\x81"
        if len(data) < 126:
            head += bytes([0x80 | len(data)])
        elif len(data) < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", len(data))
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", len(data))
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(head + mask + body)

    def _recv(self) -> dict:
        message = b""
        while True:
            b1, b2 = self._read(2)
            length = b2 & 0x7F
            if length == 126:
                (length,) = struct.unpack(">H", self._read(2))
            elif length == 127:
                (length,) = struct.unpack(">Q", self._read(8))
            payload = self._read(length)
            if b1 & 0x0F in (0, 1, 2):
                message += payload
                if b1 & 0x80:
                    return json.loads(message)

    def call(self, method: str, **params) -> dict:
        self.next_id += 1
        mine = self.next_id
        self._send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            got = self._recv()
            if got.get("id") == mine:
                if "error" in got:
                    raise RuntimeError(f"{method}: {got['error']}")
                return got["result"]

    def wait_for(self, event: str, timeout: float = 15) -> None:
        self.sock.settimeout(timeout)
        try:
            while self._recv().get("method") != event:
                pass
        except TimeoutError:
            pass
        finally:
            self.sock.settimeout(None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", help="subfolder name, e.g. before / phase2")
    parser.add_argument("--base", default="http://127.0.0.1:8421")
    parser.add_argument("--out", default="docs/facelift/shots")
    parser.add_argument("--pages", help="JSON file of {name: path}")
    parser.add_argument("--only", nargs="*", help="page names to limit to")
    parser.add_argument("--dark", action="store_true")
    args = parser.parse_args()

    pages = json.loads(Path(args.pages).read_text()) if args.pages else PAGES
    if args.only:
        pages = {k: v for k, v in pages.items() if k in args.only}
    out = Path(args.out) / args.label
    out.mkdir(parents=True, exist_ok=True)

    port = 9333
    profile = tempfile.mkdtemp(prefix="zakvaska-shots-")
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--hide-scrollbars", "--no-first-run",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    report: dict[str, dict] = {}
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        page = next(t for t in tabs if t["type"] == "page")
        ws = Socket(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        if args.dark:
            ws.call("Emulation.setEmulatedMedia",
                    features=[{"name": "prefers-color-scheme", "value": "dark"}])
        for name, path in pages.items():
            for width, height in WIDTHS.items():
                ws.call("Emulation.setDeviceMetricsOverride", width=width,
                        height=height, deviceScaleFactor=1, mobile=width < 600)
                ws.call("Page.navigate", url=args.base + path)
                ws.wait_for("Page.loadEventFired")
                time.sleep(0.5)
                probe = json.loads(
                    ws.call("Runtime.evaluate", expression=PROBE,
                            returnByValue=True)["result"]["value"])
                full = min(probe["height"], 12000)
                shot = ws.call(
                    "Page.captureScreenshot", format="png",
                    captureBeyondViewport=True,
                    clip={"x": 0, "y": 0, "width": width, "height": full, "scale": 1},
                )
                (out / f"{name}-{width}.png").write_bytes(base64.b64decode(shot["data"]))
                probe["screens"] = round(probe["height"] / height, 1)
                report[f"{name}-{width}"] = probe
                print(f"{name}-{width}: {probe['height']}px "
                      f"({probe['screens']} screens)"
                      + ("  SIDEWAYS SCROLL" if probe["pageScrollsSideways"] else ""))
    finally:
        chrome.terminate()
    (out / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
