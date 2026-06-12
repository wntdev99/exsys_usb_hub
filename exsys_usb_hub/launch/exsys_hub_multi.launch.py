"""다중 허브 launch (하위호환 별칭).

단일 노드가 이미 여러 허브를 관리하므로, 이 launch 는 통합 launch
(exsys_hub.launch.py)를 그대로 포함하는 별칭이다. 기존 명령
``ros2 launch exsys_usb_hub exsys_hub_multi.launch.py`` 호환을 위해 유지한다.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("exsys_usb_hub")
    unified = os.path.join(pkg_share, "launch", "exsys_hub.launch.py")
    default_config = os.path.join(pkg_share, "config", "exsys_hub_multi.yaml")

    config = LaunchConfiguration("config")
    return LaunchDescription([
        DeclareLaunchArgument("config", default_value=default_config,
                              description="허브 목록 YAML 경로"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(unified),
            launch_arguments={"config": config}.items(),
        ),
    ])
