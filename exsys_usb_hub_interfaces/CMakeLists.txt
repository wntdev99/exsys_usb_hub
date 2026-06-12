cmake_minimum_required(VERSION 3.8)
project(exsys_usb_hub_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/PortState.msg"
  "msg/HubStatus.msg"
  "srv/SetPort.srv"
  DEPENDENCIES std_msgs
)

ament_package()
