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

# sudo로 실행 시 실제 사용자 추적 (pip 설치 경로 등에 활용)
REAL_USER="${SUDO_USER:-$USER}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo -e "${CYAN}[setup]${NC} $*"; }
ok()    { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

require_sudo() {
    if [[ $EUID -ne 0 ]]; then
        if ! sudo -v 2>/dev/null; then
            error "sudo 권한이 필요합니다."
        fi
    fi
}

# ---------------------------------------------------------------------------
# Step 1: Platform check
# ---------------------------------------------------------------------------

info "플랫폼 확인 중..."
[[ "$(uname -s)" == "Linux" ]] || error "이 스크립트는 Linux 전용입니다."

# WSL 환경 감지
if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    error "WSL 환경은 지원하지 않습니다.\nudev가 WSL에서 동작하지 않으므로 네이티브 Linux 또는 VM을 사용하세요."
fi

# Docker/컨테이너 환경 감지
if [[ -f /.dockerenv ]] || grep -q "docker\|lxc" /proc/1/cgroup 2>/dev/null; then
    warn "컨테이너 환경이 감지되었습니다. udev 규칙이 정상 동작하지 않을 수 있습니다."
fi

# Ubuntu 버전 확인 (22.04 이상 필요 — Python 3.10+ 기본 탑재)
if command -v lsb_release &>/dev/null; then
    distro=$(lsb_release -is)
    version=$(lsb_release -rs)
    if [[ "$distro" == "Ubuntu" ]]; then
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [[ "$major" -lt 22 ]] || [[ "$major" -eq 22 && "$minor" -lt 4 ]]; then
            error "Ubuntu 22.04 이상이 필요합니다. (현재: Ubuntu $version)"
        fi
        ok "Ubuntu $version 확인"
    else
        ok "Linux ($distro $version) 확인 — Python 3.10+ 여부만 검증합니다."
    fi
else
    ok "Linux 확인"
fi

# Python 버전 확인 (3.10 이상 필요)
if ! command -v python3 &>/dev/null; then
    error "python3 를 찾을 수 없습니다."
fi
py_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
py_major=$(echo "$py_version" | cut -d. -f1)
py_minor=$(echo "$py_version" | cut -d. -f2)
if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 10 ]]; then
    error "Python 3.10 이상이 필요합니다. (현재: Python $py_version)"
fi
ok "Python $py_version 확인"

# udevadm 설치 여부 확인
if ! command -v udevadm &>/dev/null; then
    warn "udevadm 을 찾을 수 없습니다. udev 규칙 및 심링크 설정을 건너뜁니다."
    warn "설치: sudo apt install udev"
    SKIP_UDEV=1
fi

# ---------------------------------------------------------------------------
# Step 2: Python dependencies
# ---------------------------------------------------------------------------

info "Python 패키지 설치 중..."

# pip 명령어 결정 (pip3 우선, 없으면 pip)
if command -v pip3 &>/dev/null; then
    PIP=pip3
elif command -v pip &>/dev/null; then
    PIP=pip
else
    error "pip 를 찾을 수 없습니다. Python 3 환경을 확인하세요."
fi

# pyserial, pyyaml 은 시스템(apt/ROS2)에 이미 설치된 버전을 그대로 사용.
# --no-deps: 의존성 재설치 생략 → 시스템 패키지 충돌 없음
# --break-system-packages: exsys_hub 모듈 등록만을 위한 최소 사용
$PIP install --quiet -e "$SCRIPT_DIR" --no-deps --break-system-packages 2>/dev/null \
    || $PIP install --quiet -e "$SCRIPT_DIR" --no-deps
ok "exsys-hub (editable) 설치 완료 — 어디서든 import 가능"

# pyserial, pyyaml 이 실제로 import 가능한지 확인
python3 -c "import serial, yaml" 2>/dev/null \
    || warn "pyserial 또는 pyyaml 이 없습니다. 수동으로 설치하세요: sudo apt install python3-serial python3-yaml"

# ---------------------------------------------------------------------------
# Step 3: Detect connected device
# ---------------------------------------------------------------------------

info "연결된 USB-Serial 장치 감지 중..."

DETECTED_PORT=""
DETECTED_VID=""
DETECTED_PID=""
DETECTED_SERIAL=""
DETECTED_PRODUCT=""
DEVICE_COUNT=0

declare -a FOUND_PORTS=()

for port in /dev/ttyUSB* /dev/ttyACM*; do
    [[ -e "$port" ]] || continue

    vid=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{idVendor}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    pid=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{idProduct}' | head -1 | sed 's/.*=="\(.*\)"/\1/')

    if [[ -n "$vid" && -n "$pid" ]]; then
        FOUND_PORTS+=("$port")
        DEVICE_COUNT=$((DEVICE_COUNT + 1))
    fi
done

if [[ $DEVICE_COUNT -eq 0 ]]; then
    warn "연결된 USB-Serial 장치를 찾을 수 없습니다."
    warn "장치 연결 후 setup.sh 를 다시 실행하세요."
elif [[ $DEVICE_COUNT -gt 1 ]]; then
    # 여러 장치 발견 — 목록 출력 후 선택 요청
    warn "USB-Serial 장치가 ${DEVICE_COUNT}개 감지되었습니다. Exsys 허브에 해당하는 포트를 선택하세요."
    for i in "${!FOUND_PORTS[@]}"; do
        port="${FOUND_PORTS[$i]}"
        product=$(udevadm info -a -n "$port" 2>/dev/null \
            | grep 'ATTRS{product}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
        echo "  [$((i+1))] $port  ${product:-(product unknown)}"
    done
    echo -n "  선택 [1-${DEVICE_COUNT}]: "
    read -r choice
    if [[ "$choice" -ge 1 && "$choice" -le "$DEVICE_COUNT" ]] 2>/dev/null; then
        TARGET_PORT="${FOUND_PORTS[$((choice-1))]}"
    else
        error "잘못된 선택입니다."
    fi

    vid=$(udevadm info -a -n "$TARGET_PORT" 2>/dev/null \
        | grep 'ATTRS{idVendor}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    pid=$(udevadm info -a -n "$TARGET_PORT" 2>/dev/null \
        | grep 'ATTRS{idProduct}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    serial=$(udevadm info -a -n "$TARGET_PORT" 2>/dev/null \
        | grep 'ATTRS{serial}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    product=$(udevadm info -a -n "$TARGET_PORT" 2>/dev/null \
        | grep 'ATTRS{product}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    [[ "$serial" =~ ^0+$ || ${#serial} -le 1 ]] && serial=""

    DETECTED_PORT="$TARGET_PORT"
    DETECTED_VID="$vid"
    DETECTED_PID="$pid"
    DETECTED_SERIAL="$serial"
    DETECTED_PRODUCT="$product"
    ok "선택된 장치: $DETECTED_PORT"
else
    port="${FOUND_PORTS[0]}"
    vid=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{idVendor}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    pid=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{idProduct}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    serial=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{serial}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    product=$(udevadm info -a -n "$port" 2>/dev/null \
        | grep 'ATTRS{product}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    [[ "$serial" =~ ^0+$ || ${#serial} -le 1 ]] && serial=""

    DETECTED_PORT="$port"
    DETECTED_VID="$vid"
    DETECTED_PID="$pid"
    DETECTED_SERIAL="$serial"
    DETECTED_PRODUCT="$product"
    ok "장치 감지됨: $DETECTED_PORT"
fi

if [[ -n "$DETECTED_PORT" ]]; then
    echo "    Product : ${DETECTED_PRODUCT:-unknown}"
    echo "    VID     : $DETECTED_VID"
    echo "    PID     : $DETECTED_PID"
    [[ -n "$DETECTED_SERIAL" ]] && echo "    Serial  : $DETECTED_SERIAL"
fi

# ---------------------------------------------------------------------------
# Step 4: udev rule (MODE=0666 — 그룹 설정 없이 누구나 접근 가능)
# ---------------------------------------------------------------------------

if [[ -n "$DETECTED_VID" && -n "$DETECTED_PID" && -z "$SKIP_UDEV" ]]; then
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
echo -e "  실행 사용자 : $REAL_USER"
echo -e "  의존성      : pyserial, pyyaml"
[[ -n "$DETECTED_VID" && -z "$SKIP_UDEV" ]] && \
echo -e "  udev 규칙   : $UDEV_RULE_FILE"
[[ -L "$SYMLINK_PATH" ]] && \
echo -e "  심링크      : $SYMLINK_PATH"
echo -e "  설정 파일   : $SCRIPT_DIR/$CONFIG_FILE"
echo ""
echo -e "  ${CYAN}사용법:${NC}"
echo -e "    python3 exsys_cli.py status"
echo -e "    python3 exsys_cli.py on 1"
echo ""
