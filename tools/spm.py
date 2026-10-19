#!/usr/bin/env python3
"""Stand-in for the customer's Software Package Manager (SPM).

resolve  Read spm.json and make every pinned dependency available in ./deps,
         using ./spm_packages as the local cache. Missing packages are fetched
         from MinIO with the `mc` client. Every package is checked against the
         SHA-256 pinned in the manifest; anything unpinned or mismatched stops
         the build (fail closed).
"""
import hashlib, json, os, re, subprocess, sys, tarfile

MANIFEST = "spm.json"
CACHE = "spm_packages"
DEPS = "deps"
REMOTE = os.environ.get("SPM_REMOTE", "minio/spm-stable")

def fail(msg):
    print(f"SPM ERROR: {msg}")
    sys.exit(1)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def safe_extract(archive, dest):
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar.getmembers():
            target = os.path.realpath(os.path.join(dest, m.name))
            if not target.startswith(os.path.realpath(dest) + os.sep):
                fail(f"{archive} tries to write outside {dest}: {m.name}")
            if m.issym() or m.islnk():
                fail(f"{archive} contains a link, which is not allowed: {m.name}")
        tar.extractall(dest)

def resolve():
    try:
        manifest = json.load(open(MANIFEST))
    except FileNotFoundError:
        fail(f"{MANIFEST} not found")
    except json.JSONDecodeError as e:
        fail(f"{MANIFEST} is not valid JSON: {e}")
    deps = manifest.get("dependencies")
    if not isinstance(deps, list) or not deps:
        fail(f"{MANIFEST} lists no dependencies")
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(DEPS, exist_ok=True)
    hits = fetched = 0
    for d in deps:
        name, ver, pin = d.get("name"), d.get("version"), (d.get("sha256") or "").lower()
        if not name or not ver:
            fail(f"dependency entry is missing a name or version: {d}")
        if not re.fullmatch(r"[0-9a-f]{64}", pin):
            fail(f"{name} {ver} is not pinned to a SHA-256 checksum, so it cannot be verified")
        local = os.path.join(CACHE, f"{name}-{ver}.tar.gz")
        if os.path.exists(local) and sha256(local) == pin:
            hits += 1
            print(f"  cache hit   {name} {ver}")
        else:
            if os.path.exists(local):
                print(f"  cache stale {name} {ver} (checksum changed), fetching again")
                os.remove(local)
            src = f"{REMOTE}/{name}/{ver}.tar.gz"
            r = subprocess.run(["mc", "cp", "--quiet", src, local], capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"could not fetch {src}: {(r.stderr or r.stdout).strip()}")
            got = sha256(local)
            if got != pin:
                os.remove(local)
                fail(f"{name} {ver} failed its integrity check\n  expected {pin}\n  received {got}")
            fetched += 1
            print(f"  downloaded  {name} {ver}  (checksum verified)")
        dest = os.path.join(DEPS, name)
        os.makedirs(dest, exist_ok=True)
        safe_extract(local, dest)
    print(f"SPM resolve complete: {hits} from cache, {fetched} downloaded")
    print("CACHE STATE:", "warm" if fetched == 0 else ("cold" if hits == 0 else "partly warm"))

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "resolve":
        print("usage: spm.py resolve")
        sys.exit(2)
    resolve()
