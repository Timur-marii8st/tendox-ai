"""Pinned API/web overlays for manual CAPTCHA; no local migrations or broad checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

HOST = Path("/home/syurai/vibe-seller")
API_IMAGE = "vibe-seller-api:manual-captcha-20261007-v9"
WEB_IMAGE = "vibe-seller-web:manual-captcha-20261007-v9"
API_FILES = (
    "sources/supplier_serp.py",
    "sources/supplier_serp_browser.py",
    "sources/supplier_captcha_browser.py",
    "sources/supplier_captcha_recovery.py",
    "storage/supplier_captcha.py",
    "storage/eis_supplier_serp.py",
    "api/supplier_captcha.py",
    "api/discovery_runtime.py",
)
WEB_FILES = (
    "src/lib/eis-supplier-serp.ts",
    "src/lib/supplier-captcha.ts",
    "src/app/tender-discovery/captcha-actions.ts",
    "src/app/tender-discovery/captcha-assist.tsx",
    "src/app/tender-discovery/supplier-serp.tsx",
)


def docker(*args: str) -> bytes:
    return subprocess.check_output(("sudo", "-n", "docker", *args), stderr=subprocess.STDOUT)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes, old: str, new: str) -> bytes:
    if raw.count(new.encode()) == 1:
        return raw
    if raw.count(old.encode()) != 1:
        raise RuntimeError("EXACT_PATCH_CONFLICT")
    return raw.replace(old.encode(), new.encode())


def write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".captcha-tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def prepare(stage: Path):
    stage.mkdir(mode=0o700)
    manifest = {"base_images": {}, "base_files": {}, "files": {}, "images": {}}
    for service, files, root, container_root, image in (
        ("api", API_FILES, "src/procurement", "/app/src/procurement", API_IMAGE),
        ("web", WEB_FILES, "web", "/app", WEB_IMAGE),
    ):
        container = f"vibe-seller-{service}-1"
        base = docker("inspect", "--format", "{{.Image}}", container).decode().strip()
        manifest["base_images"][service] = base
        for name in files:
            target = HOST / root / name
            key = root + "/" + name
            if target.exists():
                original = target.read_bytes()
                installed = docker("exec", container, "cat", container_root + "/" + name)
                if original != installed:
                    raise RuntimeError("HOST_INSTALLED_CONFLICT:" + key)
                manifest["base_files"][key] = sha(original)
                write(stage / "backup" / key, original)
            else:
                manifest["base_files"][key] = None
            payload = stage.parent / "payload" / key
            raw = payload.read_bytes() if payload.exists() else original
            if service == "api" and name == "storage/eis_supplier_serp.py":
                local = payload.read_text()
                raw = original
                raw = patch(
                    raw,
                    "conn: Connection, company: str, now: datetime\n",
                    "conn: Connection, company: str, now: datetime,\n"
                    "    recoveries: dict[SearchEngine, datetime] | None = None,\n",
                )
                old = (
                    '            if attempt.status in {"BLOCKED", "RATE_LIMITED"} '
                    'and now - row.created_at < duration:\n'
                    '                cooldowns.add(attempt.engine)'
                )
                start = local.index(
                    "            recovered = (recoveries or {}).get(attempt.engine)"
                )
                end = local.index("    return tuple(engine for engine in ENGINES", start)
                raw = patch(raw, old, local[start:end].rstrip())
                start = local.index("            recoveries: dict[SearchEngine, datetime] = {}")
                end = local.index("            if cached is not None:", start)
                raw = patch(
                    raw,
                    "            cached = _cached(conn, company, request, current, key)\n",
                    "            cached = _cached(conn, company, request, current, key)\n"
                    + local[start:end],
                )
                raw = patch(
                    raw,
                    "if now - cached.created_at < REFRESH_COOLDOWN:",
                    "if now - cached.created_at < REFRESH_COOLDOWN and not recoveries:",
                )
                raw = patch(
                    raw,
                    "cooldowns = _budgets_and_cooldowns(conn, company, now) "
                    "if query is not None else ()",
                    "cooldowns = _budgets_and_cooldowns(conn, company, now, recoveries) "
                    "if query is not None else ()",
                )
            if service == "web" and name.endswith("/supplier-serp.tsx"):
                raw = original
                raw = patch(
                    raw,
                    'import { SupplierPage } from "./supplier-page";',
                    'import { SupplierPage } from "./supplier-page";\n'
                    'import { CaptchaAssist } from "./captcha-assist";',
                )
                raw = patch(
                    raw,
                    "    {result && <SupplierSerpReportView",
                    '    {result && <CaptchaAssist key={result.report.run_id} '
                    'request={request} result={result} onVerified={() => load("refresh")} />}\n'
                    '    {result && <SupplierSerpReportView',
                )
            if service == "web" and name == "src/lib/eis-supplier-serp.ts":
                raw = patch(
                    original,
                    "!integer(v.byte_count, 1, 2097152)",
                    "!integer(v.byte_count, 1, 8388608)",
                )
                raw = patch(raw, "!text(link.locator, 150)", "!text(link.locator, 256)")
                raw = patch(
                    raw,
                    "!link.locator.startsWith('locator(\"li.b_algo\").nth(')",
                    "!link.locator.startsWith(({ BING: 'locator(\"li.b_algo\").nth(', "
                    "YANDEX: 'locator(\"li.serp-item\").nth(', "
                    "GOOGLE: 'locator(\"#search a:has(h3)\").nth(' })[engine])",
                )
                raw = patch(
                    raw,
                    "!link.locator.startsWith(({ BING: 'locator(\"li.b_algo\").nth(', "
                    "YANDEX: 'locator(\"li.serp-item\").nth(', "
                    "GOOGLE: 'locator(\"#search a:has(h3)\").nth(' })[engine])",
                    "!(link.locator.startsWith(({ BING: 'locator(\"li.b_algo\").nth(', "
                    "YANDEX: 'locator(\"li.serp-item\").nth(', "
                    "GOOGLE: 'locator(\"#search a:has(h3)\").nth(' })[engine]) || "
                    "(engine === 'YANDEX' && link.locator.startsWith("
                    "\"locator(\\\"ul[aria-label='Результаты поиска'] > li\\\").nth(\")))",
                )
            write(stage / service / root / name, raw)
            manifest["files"][key] = sha(raw)
        context = stage / service
        destination = "/app/src/procurement/" if service == "api" else "/app/"
        source = "src/procurement/" if service == "api" else "web/"
        build = f"FROM {base}\nCOPY {source} {destination}\n"
        if service == "web":
            build += "RUN npm run build\n"
        write(context / "Dockerfile", build.encode())
        docker("build", "--pull=false", "--tag", image, str(context))
        manifest["images"][service] = (
            docker("image", "inspect", "--format", "{{.Id}}", image).decode().strip()
        )
    compose = (HOST / "docker-compose.server.yml").read_bytes()
    write(stage / "backup/compose.yml", compose)
    manifest["compose_sha256"] = sha(compose)
    write(stage / "manifest.json", json.dumps(manifest, indent=2).encode())
    docker(
        "run",
        "--rm",
        "--entrypoint",
        "python",
        API_IMAGE,
        "-c",
        "from procurement.api.discovery_runtime import create_discovery_app; "
        "import os; os.environ['EIS_PILOT_TOKEN']='x'*32; "
        "a=create_discovery_app(); "
        "assert '/v1/tender-discovery/supplier-captcha/start' in a.openapi()['paths']; "
        "print('CAPTCHA_IMPORT_PASS')",
    )
    print(json.dumps({"status": "STAGED", "manifest": str(stage / "manifest.json")}))


def require_quality_adapter() -> None:
    """ADR-0107: overlay promotion waits for its own exact candidate adapter."""
    raise RuntimeError("QUALITY_GATE_ADAPTER_UNAVAILABLE: INSTALLED_BASE_OVERLAY")


def install(stage: Path):
    require_quality_adapter()
    spec = spec_from_file_location(
        "prior_rollout", HOST / "scripts/server-supplier-browser-rollout.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    with module.deployment_lease():
        manifest = json.loads((stage / "manifest.json").read_text())
        for service, image in (("api", API_IMAGE), ("web", WEB_IMAGE)):
            if (
                docker("image", "inspect", "--format", "{{.Id}}", image).decode().strip()
                != manifest["images"][service]
            ):
                raise RuntimeError("STAGED_IMAGE_CHANGED")
            if (
                docker("inspect", "--format", "{{.Image}}", f"vibe-seller-{service}-1")
                .decode()
                .strip()
                != manifest["base_images"][service]
            ):
                raise RuntimeError("BASE_IMAGE_CHANGED")
        for name, digest in manifest["base_files"].items():
            path = HOST / name
            if (digest is None and path.exists()) or (
                digest is not None and sha(path.read_bytes()) != digest
            ):
                raise RuntimeError("BASE_SOURCE_CHANGED")
        compose = HOST / "docker-compose.server.yml"
        original = compose.read_bytes()
        if sha(original) != manifest["compose_sha256"]:
            raise RuntimeError("COMPOSE_CHANGED")
        lines = original.decode().splitlines(keepends=True)
        active = ""
        for i, line in enumerate(lines):
            if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
                active = line.strip()[:-1]
            if active in {"api", "web"} and line.startswith("    image:"):
                lines[i] = f"    image: {API_IMAGE if active == 'api' else WEB_IMAGE}\n"
            if active == "web" and line.strip() == "web:" and not any(
                candidate.startswith("    image:")
                for candidate in lines[i + 1 : next(
                    (j for j in range(i + 1, len(lines))
                     if lines[j].startswith("  ") and not lines[j].startswith("   ")
                     and lines[j].strip().endswith(":")), len(lines)
                )]
            ):
                lines[i] += f"    image: {WEB_IMAGE}\n"
        command = ("compose", "-p", "vibe-seller", "-f", str(compose))
        try:
            for name, digest in manifest["files"].items():
                service = "web" if name.startswith("web/") else "api"
                raw = (stage / service / name).read_bytes()
                if sha(raw) != digest:
                    raise RuntimeError("STAGED_SOURCE_CHANGED")
                write(HOST / name, raw)
            write(compose, "".join(lines).encode())
            docker(*command, "config", "--quiet")
            docker(*command, "up", "-d", "--no-build", "--no-deps", "api", "web")
            for name, digest in manifest["files"].items():
                service = "web" if name.startswith("web/") else "api"
                path = "/app/" + (name[4:] if service == "web" else name)
                if sha(docker("exec", f"vibe-seller-{service}-1", "cat", path)) != digest:
                    raise RuntimeError("INSTALLED_SOURCE_CONFLICT")
            print(json.dumps({"status": "INSTALLED", "images": manifest["images"]}))
        except BaseException:
            for name, digest in manifest["base_files"].items():
                if digest is None:
                    (HOST / name).unlink(missing_ok=True)
                else:
                    write(HOST / name, (stage / "backup" / name).read_bytes())
            write(compose, original)
            docker(*command, "up", "-d", "--no-build", "--no-deps", "api", "web")
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "install"))
    parser.add_argument("stage", type=Path)
    args = parser.parse_args()
    (prepare if args.mode == "prepare" else install)(args.stage)
