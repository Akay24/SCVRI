#!/usr/bin/env python3
"""SCVRI Platform health-check script."""
import subprocess, sys, os, pathlib
from typing import NamedTuple

BASE = pathlib.Path(__file__).parent.parent  # SCVRI_Platform/
SERVICES = [
    "iam", "supplier-management", "risk-intelligence",
    "visibility", "alert-engine", "integration"
]

errors = []
warnings = []

def ok(msg): print(f"  \033[32m✓\033[0m  {msg}")
def err(msg): print(f"  \033[31m✗\033[0m  {msg}"); errors.append(msg)
def warn(msg): print(f"  \033[33m⚠\033[0m  {msg}"); warnings.append(msg)

# ── 1. YAML syntax ─────────────────────────────────────────────────────────
print("\n\033[1m[1] YAML syntax — k8s manifests\033[0m")
import yaml
for f in sorted((BASE / "infra/k8s").glob("*.yaml")):
    try:
        list(yaml.safe_load_all(f.read_text()))
        ok(f"infra/k8s/{f.name}")
    except Exception as e:
        err(f"infra/k8s/{f.name}: {e}")

print("\n\033[1m[2] YAML syntax — GitHub Actions & config\033[0m")
for f in sorted(list((BASE / ".github/workflows").glob("*.yml")) +
                [BASE / ".github/dependabot.yml",
                 BASE / ".pre-commit-config.yaml",
                 BASE / "docker-compose.dev.yml"]):
    if f.exists():
        try:
            list(yaml.safe_load_all(f.read_text()))
            ok(str(f.relative_to(BASE)))
        except Exception as e:
            err(f"{f.relative_to(BASE)}: {e}")
    else:
        warn(f"Missing: {f.relative_to(BASE)}")

# ── 2. TOML syntax ─────────────────────────────────────────────────────────
print("\n\033[1m[3] TOML syntax — pyproject.toml\033[0m")
import tomllib
for f in sorted(list((BASE / "shared").glob("pyproject.toml")) +
                list((BASE / "services").rglob("pyproject.toml"))):
    try:
        tomllib.loads(f.read_text())
        ok(str(f.relative_to(BASE)))
    except Exception as e:
        err(f"{f.relative_to(BASE)}: {e}")

# ── 3. Python syntax ────────────────────────────────────────────────────────
print("\n\033[1m[4] Python syntax — all .py files\033[0m")
py_files = sorted(list((BASE / "shared").rglob("*.py")) +
                  list((BASE / "services").rglob("*.py")))
py_errors = 0
for f in py_files:
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", str(f)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        err(f"{f.relative_to(BASE)}: {r.stderr.strip()}")
        py_errors += 1
if py_errors == 0:
    ok(f"All {len(py_files)} Python files compile without errors")

# ── 4. Service structure ─────────────────────────────────────────────────────
print("\n\033[1m[5] Service structure — required files\033[0m")
for svc in SERVICES:
    base = BASE / "services" / svc
    required = [
        "Dockerfile", "pyproject.toml",
        "tests/conftest.py", "tests/__init__.py",
    ]
    missing = [r for r in required if not (base / r).exists()]
    has_src = any((base / "src").rglob("main.py"))
    if not has_src:
        missing.append("src/<pkg>/main.py")
    if missing:
        err(f"{svc}: missing {missing}")
    else:
        ok(svc)

# ── 5. K8s manifest resource inventory ──────────────────────────────────────
print("\n\033[1m[6] K8s manifests — resource inventory\033[0m")
expected_kinds = {
    "namespace.yaml": ["Namespace"],
    "configmaps.yaml": ["ConfigMap"],
    "secrets-template.yaml": ["Secret"],
    "postgresql.yaml": ["PersistentVolumeClaim", "Service", "StatefulSet"],
    "redis.yaml": ["ConfigMap", "Service", "StatefulSet"],
    "kafka.yaml": ["ConfigMap", "Service", "StatefulSet"],
    "iam.yaml": ["ServiceAccount", "Deployment", "Service", "HorizontalPodAutoscaler"],
    "ingress.yaml": ["Ingress"],
    "network-policies.yaml": ["NetworkPolicy"],
    "rbac.yaml": ["Role", "RoleBinding"],
    "pdbs.yaml": ["PodDisruptionBudget"],
    "kustomization.yaml": ["Kustomization"],
}
for fname, expected in expected_kinds.items():
    fpath = BASE / "infra/k8s" / fname
    if not fpath.exists():
        err(f"infra/k8s/{fname}: file missing")
        continue
    docs = list(yaml.safe_load_all(fpath.read_text()))
    kinds_found = [d.get("kind") for d in docs if d]
    missing_kinds = [k for k in expected if k not in kinds_found]
    if missing_kinds:
        warn(f"infra/k8s/{fname}: expected kinds {missing_kinds}, found {kinds_found}")
    else:
        ok(f"infra/k8s/{fname} ({len(docs)} resources: {', '.join(set(kinds_found))})")

# ── 6. CI/CD cross-references ────────────────────────────────────────────────
print("\n\033[1m[7] CI/CD — per-service workflow coverage\033[0m")
for svc in SERVICES:
    wf = BASE / f".github/workflows/ci-{svc}.yml"
    if wf.exists():
        content = wf.read_text()
        has_call = "_reusable-service-ci.yml" in content
        ok(f"ci-{svc}.yml {'→ calls reusable' if has_call else '(standalone)'}")
    else:
        err(f".github/workflows/ci-{svc}.yml: missing")

# ── 7. kustomization completeness ───────────────────────────────────────────
print("\n\033[1m[8] kustomization.yaml — all manifests referenced\033[0m")
kust = BASE / "infra/k8s/kustomization.yaml"
k_data = yaml.safe_load(kust.read_text())
k_resources = set(k_data.get("resources", []))
k8s_files = {f.name for f in (BASE / "infra/k8s").glob("*.yaml") if f.name != "kustomization.yaml"}
missing_in_kust = k8s_files - k_resources
extra_in_kust = k_resources - k8s_files
if missing_in_kust:
    warn(f"Not in kustomization.yaml: {sorted(missing_in_kust)}")
if extra_in_kust:
    warn(f"In kustomization.yaml but file missing: {sorted(extra_in_kust)}")
if not missing_in_kust and not extra_in_kust:
    ok(f"All {len(k8s_files)} manifest files referenced in kustomization.yaml")

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "─" * 60)
print(f"\033[1mSUMMARY\033[0m")
print(f"  Errors:   {len(errors)}")
print(f"  Warnings: {len(warnings)}")
if errors:
    print("\n\033[31mErrors to fix:\033[0m")
    for e in errors:
        print(f"  • {e}")
if warnings:
    print("\n\033[33mWarnings:\033[0m")
    for w in warnings:
        print(f"  • {w}")
if not errors:
    print("\n\033[32m✓ Platform is structurally healthy.\033[0m")
print("─" * 60)
sys.exit(1 if errors else 0)
