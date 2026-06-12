"""다중 Exsys 허브 launch — 허브마다 네임스페이스 노드 1개.

config/exsys_hub_multi.yaml 의 ``hubs`` 리스트를 읽어, 각 항목을 네임스페이스
``<name>`` 의 Lifecycle 노드로 띄우고 자동 configure→activate 한다. 코어가
허브마다 독립 인스턴스를 지원하므로(HubManager per transport), 노드도 서로
완전히 분리된다.

서비스/토픽 예 (name: hub_front)::

    /hub_front/exsys_hub_node/port_2/set
    /hub_front/exsys_hub_node/port_states

사용 예::

    ros2 launch exsys_usb_hub exsys_hub_multi.launch.py
    ros2 launch exsys_usb_hub exsys_hub_multi.launch.py config:=/path/to/hubs.yaml
"""

import os

import lifecycle_msgs.msg
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    OpaqueFunction,
    RegisterEventHandler,
)
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState


def _spawn_hubs(context, *args, **kwargs):
    cfg_path = LaunchConfiguration("config").perform(context)
    with open(cfg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    actions = []
    for hub in data.get("hubs", []):
        name = hub["name"]
        params = {k: v for k, v in hub.items() if k != "name"}

        node = LifecycleNode(
            package="exsys_usb_hub",
            executable="exsys_node",
            name="exsys_hub_node",
            namespace=name,
            output="screen",
            parameters=[params],
        )
        configure = EmitEvent(event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
        ))
        activate = RegisterEventHandler(OnStateTransition(
            target_lifecycle_node=node,
            start_state="configuring", goal_state="inactive",
            entities=[EmitEvent(event=ChangeState(
                lifecycle_node_matcher=matches_action(node),
                transition_id=lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE,
            ))],
        ))
        # 핸들러를 노드 시작 전에 등록.
        actions += [activate, node, configure]
    return actions


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("exsys_usb_hub")
    default_cfg = os.path.join(pkg_share, "config", "exsys_hub_multi.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("config", default_value=default_cfg,
                              description="다중 허브 설정 YAML 경로"),
        OpaqueFunction(function=_spawn_hubs),
    ])
