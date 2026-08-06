#!/usr/bin/env bash
# pdf-extract skill wrapper
# 路径解析：env var → config.sh → 报错
set -euo pipefail

PY="${PAPER_EXTRACT_PY:-}"
if [[ -z "$PY" ]]; then
    CONFIG="$HOME/.config/pdf-extract/config.sh"
    if [[ -f "$CONFIG" ]]; then
        # shellcheck source=/dev/null
        source "$CONFIG"
        PY="${PAPER_EXTRACT_PY:-}"
    fi
fi

if [[ -z "$PY" ]]; then
    echo "ERROR: paper-extract 未配置。请先跑：" >&2
    echo "  $(dirname "$0")/setup.sh" >&2
    exit 1
fi

exec "$PY" -m paper_extract.cli "$@"