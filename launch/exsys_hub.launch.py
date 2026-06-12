"""Exsys USB Hub 노드 launch — lifecycle 자동 configure→activate.

config/exsys_hub.yaml 의 파라미터를 주입하고, 노드를 띄운 뒤 자동으로
configure 와 activate 까지 전이시킨다. 수동 제어가 필요하면
``auto_start:=false`` 로 끄고 ``ros2 lifecycle set`` 으로 직접 전이한다.

사용 예::

    ros2 launch exsys_usb_hub exsys_hub.launch.py
    ros2 launch exsys_usb_hub exsys_hub.launch.py device_path:=/dev/ttyUSB0
    ros2 launch exsys_usb_hub exsys_hub.launch.py auto_start:=false
"""

import os

import lifecycle_msgs.msg
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("exsys_usb_hub")
    default_params = os.path.join(pkg_share, "config", "exsys_hub.yaml")

    params_file = LaunchConfiguration("params_file")
    device_path = LaunchConfiguration("device_path")
    auto_start = LaunchConfiguration("auto_start")

    node = LifecycleNode(
        package="exsys_usb_hub",
        executable="exsys_node",
        name="exsys_hub_node",
        namespace="",
        output="screen",
        parameters=[params_file, {"device_path": device_path}],
    )

    # 노드 등록 직후 configure 전이를 emit.
    configure = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
        ),
        condition=IfCondition(auto_start),
    )

    # configure 가 inactive 로 끝나면 activate 전이를 emit.
    activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=node,
            start_state="configuring",
            goal_state="inactive",
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(node),
                        transition_id=lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE,
                    )
                )
            ],
        ),
        condition=IfCondition(auto_start),
    )

    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=default_params,
                              description="파라미터 YAML 경로"),
        DeclareLaunchArgument("device_path", default_value="/dev/exsys_hub",
                              description="시리얼 포트 경로 (params_file 보다 우선)"),
        DeclareLaunchArgument("auto_start", default_value="true",
                              description="true 면 configure→activate 자동 전이"),
        activate,   # 핸들러를 노드 시작 전에 등록
        node,
        configure,
    ])
