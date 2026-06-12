"""테스트가 설치 전에도 src/ 레이아웃을 import 할 수 있게 경로를 추가한다.

colcon/ament 빌드 후에는 설치된 패키지를 쓰지만, 로컬에서 ROS 없이
``pytest`` 만 돌릴 때를 위한 보조 경로다.
"""

import os
import sys

# 로컬 테스트는 FastDDS 로 고정한다. 일부 RMW(예: 기본 설정의 CycloneDDS)에서는
# 노드 생성/discovery 가 멈출 수 있으므로, rclpy 초기화 전에 환경을 박아둔다.
# (이미 지정돼 있으면 존중)
os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")

_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
