"""Exsys USB Hub 통합 launch — 단일 노드가 1개 이상의 허브를 관리.

허브 목록 YAML(config/exsys_hub_multi.yaml 형식)을 ``config_file`` 파라미터로
주입하고, 노드를 띄운 뒤 자동으로 configure→activate 한다. 허브가 1개든 N개든
같은 launch 로 동작한다 (config 의 hubs 항목 수만 다름).

사용 예::

    ros2 launch exsys_usb_hub exsys_hub.launch.py
    ros2 launch exsys_usb_hub exsys_hub.launch.py config:=/path/to/hubs.yaml
    ros2 launch exsys_usb_hub exsys_hub.launch.py auto_start:=false
"""

import os

import lifecycle_msgs.msg
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.conditions import IfCondition
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("exsys_usb_hub")
    default_config = os.path.join(pkg_share, "config", "exsys_hub_multi.yaml")

    config = LaunchConfiguration("config")
    auto_start = LaunchConfiguration("auto_start")

    node = LifecycleNode(
        package="exsys_usb_hub",
        executable="exsys_node",
        name="exsys_hub_node",
        namespace="",
        output="screen",
        parameters=[{"config_file": config}],
    )

    configure = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
        ),
        condition=IfCondition(auto_start),
    )
    activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=node,
            start_state="configuring", goal_state="inactive",
            entities=[EmitEvent(event=ChangeState(
                lifecycle_node_matcher=matches_action(node),
                transition_id=lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE,
            ))],
        ),
        condition=IfCondition(auto_start),
    )

    return LaunchDescription([
        DeclareLaunchArgument("config", default_value=default_config,
                              description="허브 목록 YAML 경로 (hubs: [...] 형식)"),
        DeclareLaunchArgument("auto_start", default_value="true",
                              description="true 면 configure→activate 자동 전이"),
        activate, node, configure,
    ])
