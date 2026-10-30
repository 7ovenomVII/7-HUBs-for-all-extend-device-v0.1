import json
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
TARGET = os.path.join(ROOT, ".dotnet")

META = "https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/10.0/releases.json"


def main():
    os.makedirs(CACHE, exist_ok=True)
    print("Fetching release metadata...", flush=True)
    with urllib.request.urlopen(META, timeout=60) as r:
        meta = json.load(r)

    sdk_version = meta["latest-sdk"]
    print("Latest SDK:", sdk_version, flush=True)

    url = None
    for rel in meta.get("releases", []):
        sdk = rel.get("sdk") or {}
        if sdk.get("version") == sdk_version:
            for f in sdk.get("files", []):
                if f.get("rid") == "win-x64" and f.get("url", "").endswith(".zip"):
                    url = f["url"]
                    break
        if url:
            break
    if not url:
        url = f"https://dotnetcli.azureedge.net/dotnet/Sdk/{sdk_version}/dotnet-sdk-{sdk_version}-win-x64.zip"

    print("Downloading:", url, flush=True)
    zip_path = os.path.join(CACHE, f"dotnet-sdk-{sdk_version}-win-x64.zip")
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) < 100_000_000:
        req = urllib.request.Request(url, headers={"User-Agent": "7Hubs-SDK-Fetch"})
        with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            last = 0
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                pct = (done * 100 // total) if total else 0
                if pct >= last + 5:
                    last = pct
                    print(f"  {pct}% ({done // 1048576} MB / {total // 1048576} MB)", flush=True)
    print("Downloaded:", zip_path, os.path.getsize(zip_path), flush=True)

    print("Extracting to", TARGET, flush=True)
    os.makedirs(TARGET, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(TARGET)
    print("DONE", flush=True)
    print(os.path.join(TARGET, "dotnet.exe"), flush=True)


if __name__ == "__main__":
    sys.exit(main())
