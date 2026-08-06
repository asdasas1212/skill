#!/usr/bin/env bash
# Idempotent standalone runtime installer. The npm CLI uses the same layout.
set -euo pipefail

RUNTIME_HOME="${PAPER_PREREAD_HOME:-$HOME/.paper-preread}"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$RUNTIME_HOME/venv"
PY="$VENV/bin/python"
MODEL_CACHE_ROOT="${PAPER_EXTRACT_CACHE:-$RUNTIME_HOME}"
MODEL_DIR="$MODEL_CACHE_ROOT/models"

if command -v uv >/dev/null 2>&1; then
    UV=("$(command -v uv)")
else
    UV_VERSION="0.11.32"
    UV_DIR="$RUNTIME_HOME/tools/uv"
    mkdir -p "$UV_DIR"
    echo "[1/5] downloading standalone uv $UV_VERSION (no system Python needed) ..."
    curl --fail --location --retry 3 "https://astral.sh/uv/$UV_VERSION/install.sh" \
        | UV_UNMANAGED_INSTALL="$UV_DIR" UV_NO_MODIFY_PATH=1 sh
    UV=("$UV_DIR/uv")
fi

mkdir -p "$RUNTIME_HOME"
if [[ ! -x "$PY" ]]; then
    echo "[2/5] creating reusable Python 3.10 runtime at $VENV ..."
    "${UV[@]}" venv --python 3.10 "$VENV"
else
    echo "[2/5] reusing $VENV"
fi

echo "[3/5] syncing Python dependencies ..."
"${UV[@]}" pip install --python "$PY" -e "$SKILL_DIR" 'pymupdf4llm>=0.0.17'

if [[ "${PAPER_EXTRACT_SKIP_MODELS:-0}" == "1" ]]; then
    echo "[4/5] model download skipped"
else
    echo "[4/5] downloading or reusing models at $MODEL_DIR ..."
    PAPER_EXTRACT_CACHE="$MODEL_CACHE_ROOT" "$PY" -c '
from paper_extract import models
print(models.get_layout_model_path())
print(models.get_formula_det_model_path())
print(models.get_formula_rec_model_dir())
print(models.get_ocr_det_model_dir())
print(models.get_ocr_rec_model_dir())
'
fi

echo "[5/5] writing compatibility config ..."
mkdir -p "$HOME/.config/pdf-extract"
printf '%s\n' \
    "export PAPER_PREREAD_HOME=\"$RUNTIME_HOME\"" \
    "export PAPER_EXTRACT_ENV=\"$VENV\"" \
    "export PAPER_EXTRACT_PY=\"$PY\"" \
    "export PAPER_EXTRACT_CACHE=\"$MODEL_CACHE_ROOT\"" \
    > "$HOME/.config/pdf-extract/config.sh"

echo "✓ paper-extract runtime ready"
echo "  $SKILL_DIR/scripts/run.sh --help"
