#!/usr/bin/env bash
# Publish a new harzoo release to PyPI (package already exists — bump version in pyproject.toml first).
set -euo pipefail

cd "$(dirname "$0")/../.."

local_version="$(python -c "import pathlib, re; t=pathlib.Path('pyproject.toml').read_text(); m=re.search(r'^version\\s*=\\s*\"([^\"]+)\"', t, re.M); print(m.group(1) if m else '')")"
pypi_version="$(curl -fsS --max-time 15 "https://pypi.org/pypi/harzoo/json" 2>/dev/null | python -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null || true)"

if [[ -n "$pypi_version" && -n "$local_version" ]]; then
  echo "PyPI latest: $pypi_version | local pyproject.toml: $local_version"
  if [[ "$local_version" == "$pypi_version" ]]; then
    echo "ERROR: Version $local_version is already on PyPI. Bump version in pyproject.toml (e.g. 0.1.1) and try again."
    exit 1
  fi
fi

has_module() {
  python -c "import $1" 2>/dev/null
}

pip_install_build_tools() {
  echo "==> Installing build + twine (not found in current Python)"
  # Avoid broken system proxy; user can still use conda: conda install -c conda-forge python-build twine
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
    python -m pip install --upgrade pip build twine \
    -i https://pypi.org/simple/ \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org
}

ensure_build_tools() {
  if has_module build && has_module twine; then
    return 0
  fi
  pip_install_build_tools || {
    echo ""
    echo "pip install failed (often proxy/VPN). Install manually, then re-run this script:"
    echo "  conda install -y -c conda-forge python-build twine"
    echo "  # or, with proxy off:"
    echo "  pip install build twine"
    exit 1
  }
}

echo "==> Building sdist + wheel"
rm -rf build dist *.egg-info src/harzoo/*.egg-info 2>/dev/null || true
ensure_build_tools
python -m build

echo "==> Normalizing wheel/sdist metadata for PyPI"
python .github/scripts/strip_pypi_license_file.py dist/*

echo "==> Uploading to PyPI"
if [[ -z "${TWINE_PASSWORD:-}" ]]; then
  echo "Set TWINE_PASSWORD to your PyPI API token (pypi-...), then re-run:"
  echo "  export TWINE_USERNAME=__token__"
  echo "  export TWINE_PASSWORD=pypi-xxxxxxxx"
  echo "  $0"
  exit 1
fi

export TWINE_USERNAME="${TWINE_USERNAME:-__token__}"
python -m twine upload dist/*

echo "Done. Install with: pip install harzoo==${local_version}"
