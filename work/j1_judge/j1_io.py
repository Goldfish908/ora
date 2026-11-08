#!/usr/bin/env python3
"""J1 IO helper: upload/download files to /dfs/data/hewj13 via Jupyter API.

Paths are relative to the hewj13 DFS root (contents/hewj13 == /dfs/data/hewj13).
Usage: j1_io.py upload <local> <remote_rel> | download <remote_rel> <local>
"""
import base64
import json
import os
import ssl
import sys
import urllib.request

BASE = "https://modelfactory.lenovo.com"
WS_NAME = "app-workspace-1178-1789462142492"
JUP_TOKEN = "7cdkspvj"
COOKIE_FILE = "/tmp/mf_plat_cookies.txt"
PREFIX = "hewj13/"


def jwt():
    for line in open(COOKIE_FILE):
        if "aimaster-token-header" in line:
            return line.strip().split()[-1]
    raise RuntimeError("no aimaster token cookie")


def api(method, url_path, body=None):
    sep = "&" if "?" in url_path else "?"
    url = f"{BASE}/{WS_NAME}/api/{url_path}{sep}token={JUP_TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Cookie", f"aimaster-token-header={jwt()}")
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = 0
    with urllib.request.urlopen(req, context=ctx, timeout=600) as r:
        return json.loads(r.read())


def upload(local, remote):
    remote = PREFIX + remote.lstrip("/")
    size = os.path.getsize(local)
    with open(local, "rb") as f:
        data = f.read()
    body = {"content": base64.b64encode(data).decode(),
            "format": "base64", "name": os.path.basename(remote),
            "path": remote, "type": "file"}
    api("PUT", f"contents/{remote}", body)
    print(f"uploaded {local} -> /dfs/data/{remote} ({size} bytes)")


def download(remote, local):
    remote = PREFIX + remote.lstrip("/")
    meta = api("GET", f"contents/{remote}?format=base64")
    if meta.get("format") == "base64":
        payload = base64.b64decode(meta["content"])
    elif isinstance(meta.get("content"), str):
        payload = meta["content"].encode()
    elif isinstance(meta.get("content"), dict) and "cells" in meta["content"]:
        # jupytext light-format .py served as parsed notebook
        src = "".join("".join(c.get("source", [])) + "\n\n"
                      for c in meta["content"]["cells"])
        payload = src.encode()
    else:
        raise RuntimeError(f"unexpected content format: {meta.get('format')}")
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    with open(local, "wb") as f:
        f.write(payload)
    print(f"downloaded /dfs/data/{remote} -> {local} ({len(payload)} bytes)")


if __name__ == "__main__":
    if sys.argv[1] == "upload":
        upload(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "download":
        download(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("usage: upload|download")
