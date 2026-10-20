"""Stage Caddy config on the VPS without activating public access."""

import hashlib
import secrets
import subprocess
from pathlib import Path

root = Path("/home/syurai/vibe-seller-state/domain-syurai-ru")
root.mkdir(mode=0o700, exist_ok=True)
original = Path("/opt/forgejo/Caddyfile").read_text()
if "syurai.ru {" in original or (root / "access.txt").exists():
    raise SystemExit("Existing domain setup found; inspect before changing")
password = secrets.token_urlsafe(24)
hashed = subprocess.run(
    ["sudo", "-n", "docker", "exec", "-i", "forgejo-caddy", "caddy", "hash-password"],
    input=password + "\n",
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()
block = """
syurai.ru {
    encode zstd gzip
    header {
        -Server
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer"
        X-Frame-Options "SAMEORIGIN"
    }
    basic_auth {
        pilot HASH
    }
    @root path /
    redir @root /tender-discovery 302
    reverse_proxy vibe-seller-web-1:3000 {
        header_up -Authorization
    }
}
""".replace("HASH", hashed)
files = {
    "Caddyfile.before": original,
    "Caddyfile.proposed": original + block,
    "access.txt": "URL: https://syurai.ru/tender-discovery\nLogin: pilot\nPassword: "
    + password
    + "\n",
    "compose.domain.yaml": """services:
  caddy:
    networks:
      - forgejo
      - procurement
networks:
  procurement:
    external: true
    name: vibe-seller_default
""",
}
for name, data in files.items():
    path = root / name
    path.write_text(data)
    path.chmod(0o600)
print("Staged config SHA256:", hashlib.sha256((original + block).encode()).hexdigest())
