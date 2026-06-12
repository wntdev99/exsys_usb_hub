"""exsys_usb_hub — Exsys 관리형 USB 허브 제어 패키지.

계층 구조
---------
- ``exsys_usb_hub.core``  : ROS 비의존 코어 (프로토콜·시리얼·안전정책).
                            노트북/테스트 벤치에서도 독립 동작한다.
- ``exsys_usb_hub.ros``   : 코어를 감싸는 ROS2 어댑터 (rclpy 노드).
- ``exsys_usb_hub.cli``   : ROS 없이 터미널에서 쓰는 CLI.
"""
