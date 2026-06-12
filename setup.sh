#!/bin/bash
# Exsys USB Hub — setup 스크립트 (ROS2 ament_python 패키지)
# udev 규칙/심링크를 설정하고 colcon 으로 패키지를 빌드한다.

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
PKG_NAME="exsys_usb_hub"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 패키지는 <workspace>/src/<pkg> 에 위치 → 워크스페이스 루트는 두 단계 위.
WS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

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

# WSL 환경 감지 (udev 미동작)
if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    error "WSL 환경은 지원하지 않습니다.\nudev 가 동작하지 않으므로 네이티브 Linux 또는 VM 을 사용하세요."
fi

# Docker/컨테이너 환경 감지
if [[ -f /.dockerenv ]] || grep -q "docker\|lxc" /proc/1/cgroup 2>/dev/null; then
    warn "컨테이너 환경이 감지되었습니다. udev 규칙이 정상 동작하지 않을 수 있습니다."
fi

# Python 버전 확인 (3.10 이상)
command -v python3 &>/dev/null || error "python3 를 찾을 수 없습니다."
py_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
py_major=${py_version%.*}; py_minor=${py_version#*.}
if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 10 ]]; then
    error "Python 3.10 이상이 필요합니다. (현재: Python $py_version)"
fi
ok "Python $py_version 확인"

# udevadm 설치 여부
if ! command -v udevadm &>/dev/null; then
    warn "udevadm 을 찾을 수 없습니다. udev 규칙/심링크 설정을 건너뜁니다 (설치: sudo apt install udev)."
    SKIP_UDEV=1
fi

# ---------------------------------------------------------------------------
# Step 2: ROS2 환경 확인
# ---------------------------------------------------------------------------

info "ROS2 환경 확인 중..."

# ROS_DISTRO 가 비어 있으면 /opt/ros 에서 가장 최신 배포판을 자동 선택.
if [[ -z "$ROS_DISTRO" ]]; then
    if compgen -G "/opt/ros/*/setup.bash" > /dev/null; then
        ROS_DISTRO="$(basename "$(ls -d /opt/ros/*/ | sort | tail -1)")"
        warn "ROS_DISTRO 가 설정되지 않아 '$ROS_DISTRO' 를 사용합니다."
    fi
fi

if [[ -n "$ROS_DISTRO" && -f "/opt/ros/$ROS_DISTRO/setup.bash" ]]; then
    # shellcheck disable=SC1090
    source "/opt/ros/$ROS_DISTRO/setup.bash"
    ok "ROS2 $ROS_DISTRO 확인"
else
    warn "ROS2 설치를 찾지 못했습니다. colcon 빌드를 건너뜁니다."
    SKIP_BUILD=1
fi

# pyserial, pyyaml import 확인 (rosdep/apt 로 설치되는 시스템 패키지)
python3 -c "import serial, yaml" 2>/dev/null \
    || warn "pyserial/pyyaml 이 없습니다. 설치: sudo apt install python3-serial python3-yaml"

# ---------------------------------------------------------------------------
# Step 3: Detect connected device
# ---------------------------------------------------------------------------

info "연결된 USB-Serial 장치 감지 중..."

DETECTED_PORT=""; DETECTED_VID=""; DETECTED_PID=""; DETECTED_SERIAL=""; DETECTED_PRODUCT=""
DEVICE_COUNT=0
declare -a FOUND_PORTS=()

for port in /dev/ttyUSB* /dev/ttyACM*; do
    [[ -e "$port" ]] || continue
    vid=$(udevadm info -a -n "$port" 2>/dev/null | grep 'ATTRS{idVendor}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    pid=$(udevadm info -a -n "$port" 2>/dev/null | grep 'ATTRS{idProduct}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    if [[ -n "$vid" && -n "$pid" ]]; then
        FOUND_PORTS+=("$port"); DEVICE_COUNT=$((DEVICE_COUNT + 1))
    fi
done

_read_attrs() {  # $1 = port
    DETECTED_PORT="$1"
    DETECTED_VID=$(udevadm info -a -n "$1" 2>/dev/null | grep 'ATTRS{idVendor}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    DETECTED_PID=$(udevadm info -a -n "$1" 2>/dev/null | grep 'ATTRS{idProduct}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    local serial product
    serial=$(udevadm info -a -n "$1" 2>/dev/null | grep 'ATTRS{serial}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    product=$(udevadm info -a -n "$1" 2>/dev/null | grep 'ATTRS{product}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
    [[ "$serial" =~ ^0+$ || ${#serial} -le 1 ]] && serial=""
    DETECTED_SERIAL="$serial"; DETECTED_PRODUCT="$product"
}

if [[ $DEVICE_COUNT -eq 0 ]]; then
    warn "연결된 USB-Serial 장치를 찾을 수 없습니다. 장치 연결 후 다시 실행하세요."
elif [[ $DEVICE_COUNT -gt 1 ]]; then
    warn "USB-Serial 장치가 ${DEVICE_COUNT}개 감지되었습니다. Exsys 허브 포트를 선택하세요."
    for i in "${!FOUND_PORTS[@]}"; do
        port="${FOUND_PORTS[$i]}"
        product=$(udevadm info -a -n "$port" 2>/dev/null | grep 'ATTRS{product}' | head -1 | sed 's/.*=="\(.*\)"/\1/')
        echo "  [$((i+1))] $port  ${product:-(product unknown)}"
    done
    echo -n "  선택 [1-${DEVICE_COUNT}]: "; read -r choice
    if [[ "$choice" -ge 1 && "$choice" -le "$DEVICE_COUNT" ]] 2>/dev/null; then
        _read_attrs "${FOUND_PORTS[$((choice-1))]}"
    else
        error "잘못된 선택입니다."
    fi
    ok "선택된 장치: $DETECTED_PORT"
else
    _read_attrs "${FOUND_PORTS[0]}"
    ok "장치 감지됨: $DETECTED_PORT"
fi

if [[ -n "$DETECTED_PORT" ]]; then
    echo "    Product : ${DETECTED_PRODUCT:-unknown}"
    echo "    VID     : $DETECTED_VID"
    echo "    PID     : $DETECTED_PID"
    [[ -n "$DETECTED_SERIAL" ]] && echo "    Serial  : $DETECTED_SERIAL"
fi

# ---------------------------------------------------------------------------
# Step 4: udev rule (MODE=0666, /dev/exsys_hub 고정 심링크)
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
    [[ -f "$UDEV_RULE_FILE" ]] && warn "$UDEV_RULE_FILE 이미 존재합니다. 덮어씁니다."

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
        warn "$SYMLINK_PATH 심링크가 아직 없습니다. 장치를 다시 꽂으면 적용됩니다."
    fi
fi

# ---------------------------------------------------------------------------
# Step 5: colcon build
# ---------------------------------------------------------------------------

if [[ -z "$SKIP_BUILD" ]]; then
    if ! command -v colcon &>/dev/null; then
        warn "colcon 미설치 — 빌드를 건너뜁니다. 설치: sudo apt install python3-colcon-common-extensions"
    elif [[ ! -d "$WS_ROOT/src" ]]; then
        warn "colcon 워크스페이스 루트를 찾지 못했습니다 ($WS_ROOT). 수동으로 빌드하세요."
    else
        info "colcon 빌드 중: $WS_ROOT (패키지: $PKG_NAME)"
        ( cd "$WS_ROOT" && colcon build --packages-select "$PKG_NAME" )
        ok "빌드 완료 — 사용 전: source $WS_ROOT/install/setup.bash"
    fi
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
[[ -n "$ROS_DISTRO" ]] && echo -e "  ROS2        : $ROS_DISTRO"
[[ -n "$DETECTED_VID" && -z "$SKIP_UDEV" ]] && echo -e "  udev 규칙   : $UDEV_RULE_FILE"
[[ -L "$SYMLINK_PATH" ]] && echo -e "  심링크      : $SYMLINK_PATH"
echo ""
echo -e "  ${CYAN}ROS2 사용법:${NC}"
echo -e "    source $WS_ROOT/install/setup.bash"
echo -e "    ros2 launch $PKG_NAME exsys_hub.launch.py"
echo -e "    ros2 service call /exsys_hub_node/port_2/set std_srvs/srv/SetBool \"{data: false}\""
echo -e "    ros2 topic echo /exsys_hub_node/port_states"
echo ""
echo -e "  ${CYAN}ROS 없이 (CLI):${NC}"
echo -e "    ros2 run $PKG_NAME exsys_cli status      # 또는 install/.../exsys_cli"
echo -e "    ros2 run $PKG_NAME exsys_cli on 1"
echo ""
