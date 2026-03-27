#!/bin/bash
# Exsys USB Hub — setup script
# Installs dependencies, configures udev rules, and creates a default config.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

UDEV_RULE_FILE="/etc/udev/rules.d/99-exsys-hub.rules"
SYMLINK_NAME="exsys_hub"
SYMLINK_PATH="/dev/${SYMLINK_NAME}"
CONFIG_FILE="exsys_hub.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo -e "${CYAN}[setup]${NC} $*"; }
ok()    { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

require_sudo() {
    if ! sudo -v 2>/dev/null; then
        error "sudo 권한이 필요합니다."
    fi
}

# ---------------------------------------------------------------------------
# Step 1: Platform check
# ---------------------------------------------------------------------------

info "플랫폼 확인 중..."
[[ "$(uname -s)" == "Linux" ]] || error "이 스크립트는 Linux 전용입니다."
ok "Linux 확인"

# ---------------------------------------------------------------------------
# Step 2: Python dependencies
# ---------------------------------------------------------------------------

info "Python 패키지 설치 중 (pyserial, pyyaml)..."

if command -v pip3 &>/dev/null; then
    pip3 install --quiet pyserial pyyaml --break-system-packages 2>/dev/null \
        || pip3 install --quiet pyserial pyyaml
    ok "pyserial, pyyaml 설치 완료"
else
    error "pip3 를 찾을 수 없습니다. Python 3 환경을 확인하세요."
fi

# ---------------------------------------------------------------------------
# Step 3: Detect connected device
# ---------------------------------------------------------------------------

info "연결된 USB-Serial 장치 감지 중..."

DETECTED_PORT=""
DETECTED_VID=""
DETECTED_PID=""
DETECTED_SERIAL=""
DETECTED_PRODUCT=""

for port in /dev/ttyUSB* /dev/ttyACM*; do
    [[ -e "$port" ]] || continue

    vid=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{idVendor}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    pid=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{idProduct}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    serial=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{serial}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    product=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{product}' | head -1 | sed 's/.*=="\(.*\)"/\1/')

    # 시리얼이 전부 0이거나 너무 짧으면 무의미 — 제거
    if [[ "$serial" =~ ^0+$ || ${#serial} -le 1 ]]; then
        serial=""
    fi

    if [[ -n "$vid" && -n "$pid" ]]; then
        DETECTED_PORT="$port"
        DETECTED_VID="$vid"
        DETECTED_PID="$pid"
        DETECTED_SERIAL="$serial"
        DETECTED_PRODUCT="$product"
        break
    fi
done

if [[ -n "$DETECTED_PORT" ]]; then
    ok "장치 감지됨: $DETECTED_PORT"
    echo "    Product : ${DETECTED_PRODUCT:-unknown}"
    echo "    VID     : $DETECTED_VID"
    echo "    PID     : $DETECTED_PID"
    [[ -n "$DETECTED_SERIAL" ]] && echo "    Serial  : $DETECTED_SERIAL"
else
    warn "연결된 USB-Serial 장치를 찾을 수 없습니다."
    warn "udev 규칙 없이 계속합니다. 장치 연결 후 setup.sh 를 다시 실행하세요."
fi

# ---------------------------------------------------------------------------
# Step 4: udev rule (MODE=0666 — 그룹 설정 없이 누구나 접근 가능)
# ---------------------------------------------------------------------------

if [[ -n "$DETECTED_VID" && -n "$DETECTED_PID" ]]; then
    info "udev 규칙 생성 중: $UDEV_RULE_FILE"

    if [[ -n "$DETECTED_SERIAL" ]]; then
        RULE='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$DETECTED_VID"'", ATTRS{idProduct}=="'"$DETECTED_PID"'", ATTRS{serial}=="'"$DETECTED_SERIAL"'", SYMLINK+="'"$SYMLINK_NAME"'", MODE="0666"'
        MATCH_DESC="VID:PID:Serial (장치 고유)"
    else
        RULE='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$DETECTED_VID"'", ATTRS{idProduct}=="'"$DETECTED_PID"'", SYMLINK+="'"$SYMLINK_NAME"'", MODE="0666"'
        MATCH_DESC="VID:PID"
    fi

    if [[ -f "$UDEV_RULE_FILE" ]]; then
        warn "$UDEV_RULE_FILE 이미 존재합니다. 덮어씁니다."
    fi

    require_sudo
    echo "$RULE" | sudo tee "$UDEV_RULE_FILE" > /dev/null
    ok "udev 규칙 작성 완료 (매칭: $MATCH_DESC, MODE=0666)"

    sudo udevadm control --reload-rules
    sudo udevadm trigger
    ok "udev 규칙 적용 완료"

    sleep 1
    if [[ -L "$SYMLINK_PATH" ]]; then
        ok "심링크 확인: $SYMLINK_PATH -> $(readlink -f "$SYMLINK_PATH")"
    else
        warn "$SYMLINK_PATH 심링크가 아직 생성되지 않았습니다."
        warn "장치를 USB 포트에서 뽑았다가 다시 꽂으면 적용됩니다."
    fi
fi

# ---------------------------------------------------------------------------
# Step 5: Default config
# ---------------------------------------------------------------------------

info "설정 파일 확인 중: $SCRIPT_DIR/$CONFIG_FILE"

if [[ -f "$SCRIPT_DIR/$CONFIG_FILE" ]]; then
    ok "설정 파일 이미 존재함 — 건너뜀"
else
    if [[ -L "$SYMLINK_PATH" || -n "$DETECTED_VID" ]]; then
        DEFAULT_PORT="$SYMLINK_PATH"
    elif [[ -n "$DETECTED_PORT" ]]; then
        DEFAULT_PORT="$DETECTED_PORT"
    else
        DEFAULT_PORT="/dev/ttyUSB0"
    fi

    python3 - <<PYEOF
import sys
sys.path.insert(0, "$SCRIPT_DIR")
from exsys_hub import HubConfig
cfg = HubConfig.default()
cfg.serial_port = "$DEFAULT_PORT"
cfg.save("$SCRIPT_DIR/$CONFIG_FILE")
print(f"    포트: $DEFAULT_PORT")
PYEOF
    ok "설정 파일 생성 완료: $SCRIPT_DIR/$CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo -e "${BOLD}=============================${NC}"
echo -e "${GREEN}${BOLD}  Setup 완료${NC}"
echo -e "${BOLD}=============================${NC}"
echo ""
echo -e "  의존성     : pyserial, pyyaml"
[[ -n "$DETECTED_VID" ]] && \
echo -e "  udev 규칙  : $UDEV_RULE_FILE"
[[ -L "$SYMLINK_PATH" ]] && \
echo -e "  심링크     : $SYMLINK_PATH"
echo -e "  설정 파일  : $SCRIPT_DIR/$CONFIG_FILE"
echo ""
echo -e "  ${CYAN}사용법:${NC}"
echo -e "    python3 exsys_cli.py status"
echo -e "    python3 exsys_cli.py on 1"
echo ""
