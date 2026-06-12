import os
from glob import glob

from setuptools import find_packages, setup

package_name = "exsys_usb_hub"

setup(
    name=package_name,
    version="2.0.0",
    # src-layout: import 패키지는 src/ 밑에 있다.
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    data_files=[
        ("share/ament_index/resource_index/packages",
            ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"),
            glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"),
            glob("config/*.yaml")),
    ],
    install_requires=["setuptools", "pyserial", "pyyaml"],
    zip_safe=True,
    maintainer="jeongmin.choi",
    maintainer_email="jeongmin.choi@wattrobotics.ai",
    description="Exsys 관리형 USB 허브 포트 전원 제어 (ROS 비의존 코어 + ROS2 노드).",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # ROS2: ros2 run exsys_usb_hub exsys_node
            "exsys_node = exsys_usb_hub.ros.node:main",
            # ROS 없이도 실행 가능한 CLI
            "exsys_cli = exsys_usb_hub.cli:main",
        ],
    },
)
