#!/bin/bash
# Exsys USB Hub — setup 스크립트 (ROS2 ament_python 패키지, 다중 허브 지원)
# udev 규칙/심링크를 설정하고 colcon 으로 패키지를 빌드한다.
#
# 다중 허브: 관리 인터페이스는 FTDI FT232R(0403:6001) 범용 칩이라 VID:PID 로는
# 구분 불가하며, 유일한 식별자는 FT232R 의 serial 이다. 따라서 허브마다
# /dev/exsys_hub-<serial> 고정 심링크를 만든다(serial 기반이라 다른 FTDI 장치
# 오인식도 방지). 단일 허브일 때는 /dev/exsys_hub 도 함께 만들어 하위호환을 유지.

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

UDEV_RULE_FILE="/etc/udev/rules.d/99-exsys-hub.rules"
PKG_NAME="exsys_usb_hub"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"   # <workspace>/src/<pkg> → 두 단계 위
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
        sudo -v 2>/dev/null || error "sudo 권한이 필요합니다."
    fi
}

# udevadm 단일 속성 추출: _attr <port> <key>
_attr() {
    udevadm info -a -n "$1" 2>/dev/null | grep "ATTRS{$2}" | head -1 | sed 's/.*=="\(.*\)"/\1/'
}

# ---------------------------------------------------------------------------
# Step 1: Platform check
# ---------------------------------------------------------------------------

info "플랫폼 확인 중..."
[[ "$(uname -s)" == "Linux" ]] || error "이 스크립트는 Linux 전용입니다."

if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
    error "WSL 환경은 지원하지 않습니다.\nudev 가 동작하지 않으므로 네이티브 Linux 또는 VM 을 사용하세요."
fi
if [[ -f /.dockerenv ]] || grep -q "docker\|lxc" /proc/1/cgroup 2>/dev/null; then
    warn "컨테이너 환경이 감지되었습니다. udev 규칙이 정상 동작하지 않을 수 있습니다."
fi

command -v python3 &>/dev/null || error "python3 를 찾을 수 없습니다."
py_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
py_major=${py_version%.*}; py_minor=${py_version#*.}
if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 10 ]]; then
    error "Python 3.10 이상이 필요합니다. (현재: Python $py_version)"
fi
ok "Python $py_version 확인"

if ! command -v udevadm &>/dev/null; then
    warn "udevadm 을 찾을 수 없습니다. udev 규칙/심링크 설정을 건너뜁니다 (설치: sudo apt install udev)."
    SKIP_UDEV=1
fi

# ---------------------------------------------------------------------------
# Step 2: ROS2 환경 확인
# ---------------------------------------------------------------------------

info "ROS2 환경 확인 중..."
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
python3 -c "import serial, yaml" 2>/dev/null \
    || warn "pyserial/pyyaml 이 없습니다. 설치: sudo apt install python3-serial python3-yaml"

# ---------------------------------------------------------------------------
# Step 3: Detect connected device(s) — 다중 선택 지원
# ---------------------------------------------------------------------------

info "연결된 USB-Serial 장치 감지 중..."

declare -a FOUND_PORTS=()
for port in /dev/ttyUSB* /dev/ttyACM*; do
    [[ -e "$port" ]] || continue
    [[ -n "$(_attr "$port" idVendor)" && -n "$(_attr "$port" idProduct)" ]] && FOUND_PORTS+=("$port")
done
DEVICE_COUNT=${#FOUND_PORTS[@]}

declare -a SELECTED_PORTS=()
if [[ $DEVICE_COUNT -eq 0 ]]; then
    warn "연결된 USB-Serial 장치를 찾을 수 없습니다. 장치 연결 후 다시 실행하세요."
elif [[ $DEVICE_COUNT -eq 1 ]]; then
    SELECTED_PORTS=("${FOUND_PORTS[0]}")
    ok "장치 감지됨: ${FOUND_PORTS[0]}"
else
    warn "USB-Serial 장치가 ${DEVICE_COUNT}개 감지되었습니다. Exsys 허브 포트를 선택하세요 (다중 허브 가능)."
    for i in "${!FOUND_PORTS[@]}"; do
        port="${FOUND_PORTS[$i]}"
        echo "  [$((i+1))] $port  $(_attr "$port" product || echo '(product unknown)')  serial=$(_attr "$port" serial)"
    done
    echo -n "  선택 (쉼표 구분, 예: 1,3 / 전체: a): "; read -r choice
    if [[ "$choice" == "a" || "$choice" == "A" ]]; then
        SELECTED_PORTS=("${FOUND_PORTS[@]}")
    else
        IFS=',' read -ra picks <<< "$choice"
        for p in "${picks[@]}"; do
            p="${p// /}"
            [[ "$p" -ge 1 && "$p" -le "$DEVICE_COUNT" ]] 2>/dev/null || error "잘못된 선택: '$p'"
            SELECTED_PORTS+=("${FOUND_PORTS[$((p-1))]}")
        done
    fi
    ok "선택된 허브 ${#SELECTED_PORTS[@]}개: ${SELECTED_PORTS[*]}"
fi

# ---------------------------------------------------------------------------
# Step 4: udev rules — 허브마다 per-serial 심링크
# ---------------------------------------------------------------------------

declare -a CREATED_LINKS=()
if [[ ${#SELECTED_PORTS[@]} -gt 0 && -z "$SKIP_UDEV" ]]; then
    MULTI=$([[ ${#SELECTED_PORTS[@]} -gt 1 ]] && echo 1 || echo 0)
    RULES=""
    for port in "${SELECTED_PORTS[@]}"; do
        vid=$(_attr "$port" idVendor); pid=$(_attr "$port" idProduct); serial=$(_attr "$port" serial)
        [[ "$serial" =~ ^0+$ || ${#serial} -le 1 ]] && serial=""

        if [[ -n "$serial" ]]; then
            link="exsys_hub-${serial}"
            symlinks="$link"
            # 단일 허브면 /dev/exsys_hub 도 함께 (하위호환)
            [[ "$MULTI" -eq 0 ]] && symlinks="$link exsys_hub"
            RULES+='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$vid"'", ATTRS{idProduct}=="'"$pid"'", ATTRS{serial}=="'"$serial"'", SYMLINK+="'"$symlinks"'", MODE="0666"'$'\n'
            CREATED_LINKS+=("/dev/$link"); [[ "$MULTI" -eq 0 ]] && CREATED_LINKS+=("/dev/exsys_hub")
            ok "규칙 준비: $port → /dev/$link (serial=$serial)"
        elif [[ "$MULTI" -eq 0 ]]; then
            # serial 없음 + 단일 허브: VID:PID 폴백 (주의: 다른 FTDI 장치도 매칭될 수 있음)
            warn "$port 에 serial 이 없어 VID:PID 규칙으로 폴백합니다 (다른 FTDI 장치 오인식 주의)."
            RULES+='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$vid"'", ATTRS{idProduct}=="'"$pid"'", SYMLINK+="exsys_hub", MODE="0666"'$'\n'
            CREATED_LINKS+=("/dev/exsys_hub")
        else
            warn "$port 에 serial 이 없어 다중 허브 구분이 불가능합니다 — 이 장치는 건너뜁니다."
        fi
    done

    if [[ -n "$RULES" ]]; then
        [[ -f "$UDEV_RULE_FILE" ]] && warn "$UDEV_RULE_FILE 이미 존재합니다. 덮어씁니다."
        require_sudo
        printf '%s' "$RULES" | sudo tee "$UDEV_RULE_FILE" > /dev/null
        ok "udev 규칙 작성 완료 (MODE=0666, ${#SELECTED_PORTS[@]}개 허브)"
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        ok "udev 규칙 적용 완료"
        sleep 1
        for link in "${CREATED_LINKS[@]}"; do
            [[ -L "$link" ]] && ok "심링크 확인: $link -> $(readlink -f "$link")" \
                             || warn "$link 아직 없음 — 장치를 다시 꽂으면 적용됩니다."
        done
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
if [[ ${#CREATED_LINKS[@]} -gt 0 ]]; then
    echo -e "  심링크      :"
    for link in "${CREATED_LINKS[@]}"; do echo -e "                $link"; done
fi
echo ""
echo -e "  ${CYAN}단일 허브:${NC}"
echo -e "    source $WS_ROOT/install/setup.bash"
echo -e "    ros2 launch $PKG_NAME exsys_hub.launch.py"
echo ""
if [[ ${#SELECTED_PORTS[@]} -gt 1 ]]; then
echo -e "  ${CYAN}다중 허브:${NC} config/exsys_hub_multi.yaml 의 device_path 를 위 심링크로 채운 뒤"
echo -e "    ros2 launch $PKG_NAME exsys_hub_multi.launch.py"
echo ""
fi
echo -e "  ${CYAN}ROS 없이 (CLI):${NC}"
echo -e "    ros2 run $PKG_NAME exsys_cli -p ${CREATED_LINKS[0]:-/dev/exsys_hub} status"
echo ""
