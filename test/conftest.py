"""테스트가 설치 전에도 src/ 레이아웃을 import 할 수 있게 경로를 추가한다.

colcon/ament 빌드 후에는 설치된 패키지를 쓰지만, 로컬에서 ROS 없이
``pytest`` 만 돌릴 때를 위한 보조 경로다.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
