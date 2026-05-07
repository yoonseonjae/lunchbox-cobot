#
#  m0609_rg2_combined launch file
#  Based on dsr_bringup2_rviz.launch.py but uses the combined M0609+RG2 URDF
#

import os

from launch import LaunchDescription
from launch.actions import RegisterEventHandler, DeclareLaunchArgument, GroupAction
from launch.event_handlers import OnProcessExit
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution, LaunchConfiguration, PythonExpression
from launch.conditions import IfCondition, UnlessCondition

from launch_ros.actions import Node, SetRemap
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from dsr_bringup2.utils import read_update_rate, show_git_info


def generate_launch_description():
    ARGUMENTS = [
        DeclareLaunchArgument('name',  default_value='dsr01',       description='NAME_SPACE'),
        DeclareLaunchArgument('host',  default_value='127.0.0.1',   description='ROBOT_IP'),
        DeclareLaunchArgument('port',  default_value='12345',       description='ROBOT_PORT'),
        DeclareLaunchArgument('mode',  default_value='virtual',     description='OPERATION MODE'),
        DeclareLaunchArgument('model', default_value='m0609',       description='ROBOT_MODEL'),
        DeclareLaunchArgument('color', default_value='white',       description='ROBOT_COLOR'),
        DeclareLaunchArgument('gui',   default_value='false',       description='Start RViz2'),
        DeclareLaunchArgument('rt_host', default_value='192.168.137.50', description='ROBOT_RT_IP'),
        DeclareLaunchArgument('remap_tf', default_value='false',    description='REMAP TF'),
    ]

    mode = LaunchConfiguration("mode")
    update_rate = str(read_update_rate())
    show_git_info()

    # ── Doosan controller uses xacro from dsr_description2 (for ros2_control) ──
    xacro_path = os.path.join(get_package_share_directory('dsr_description2'), 'xacro')

    robot_description_content = Command([
        PathJoinSubstitution([FindExecutable(name="xacro")]),
        " ",
        PathJoinSubstitution([
            FindPackageShare("dsr_description2"), "xacro",
            LaunchConfiguration('model'),
        ]),
        ".urdf.xacro",
        " name:=",       LaunchConfiguration('name'),
        " host:=",       LaunchConfiguration('host'),
        " rt_host:=",    LaunchConfiguration('rt_host'),
        " port:=",       LaunchConfiguration('port'),
        " mode:=",       LaunchConfiguration('mode'),
        " model:=",      LaunchConfiguration('model'),
        " update_rate:=", update_rate,
    ])

    robot_description = {"robot_description": robot_description_content}

    robot_controllers = [
        PathJoinSubstitution([
            FindPackageShare("dsr_controller2"), "config", "dsr_update_rate.yaml",
        ]),
        PathJoinSubstitution([
            FindPackageShare("dsr_controller2"), "config", "dsr_controller2.yaml",
        ]),
    ]

    # ── RViz uses the combined URDF (M0609 + RG2 gripper) ──
    rg2_urdf_path = os.path.join(
        get_package_share_directory('m0609_rg2_combined'), 'm0609_rg2.urdf')

    # Read URDF content for robot_state_publisher
    with open(rg2_urdf_path, 'r') as f:
        rg2_urdf_content = f.read()

    rviz_config_file = PathJoinSubstitution([
        FindPackageShare("m0609_rg2_combined"), "rviz", "default.rviz",
    ])

    # ── Nodes ──

    run_emulator_node = Node(
        package="dsr_bringup2",
        executable="run_emulator",
        namespace=LaunchConfiguration('name'),
        parameters=[
            {"name":    LaunchConfiguration('name')},
            {"rate":    100},
            {"standby": 5000},
            {"command": True},
            {"host":    LaunchConfiguration('host')},
            {"port":    LaunchConfiguration('port')},
            {"mode":    LaunchConfiguration('mode')},
            {"model":   LaunchConfiguration('model')},
            {"gripper": "none"},
            {"mobile":  "none"},
            {"rt_host": LaunchConfiguration('rt_host')},
        ],
        condition=IfCondition(PythonExpression(["'", mode, "' == 'virtual'"])),
        output="screen",
    )

    control_node = Node(
        package="controller_manager",
        executable="ros2_control_node",
        namespace=LaunchConfiguration('name'),
        parameters=[robot_description] + robot_controllers,
        output="both",
    )

    # robot_state_publisher uses the combined URDF with gripper
    # joint_state_publisher to merge robot joints and provide default values for gripper joints
    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        namespace=LaunchConfiguration('name'),
        parameters=[{
            'source_list': ['joint_states'], # Listen to the controller's joint states
            'rate': 30
        }],
        remappings=[('joint_states', 'joint_states_combined')]
    )

    # robot_state_publisher uses the combined URDF with gripper
    robot_state_pub_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        namespace=LaunchConfiguration('name'),
        output='both',
        parameters=[{'robot_description': rg2_urdf_content}],
        remappings=[('joint_states', 'joint_states_combined')]
    )

    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        namespace=LaunchConfiguration('name'),
        name="rviz2",
        output="log",
        arguments=["-d", rviz_config_file],
        condition=IfCondition(LaunchConfiguration('gui')),
    )

    original_tf_nodes = GroupAction(
        actions=[
            joint_state_publisher_node,
            robot_state_pub_node,
            rviz_node
        ],
        condition=UnlessCondition(LaunchConfiguration('remap_tf')),
    )

    remapped_tf_nodes = GroupAction(
        actions=[
            SetRemap(src='/tf', dst='tf'),
            SetRemap(src='/tf_static', dst='tf_static'),
            joint_state_publisher_node,
            robot_state_pub_node,
            rviz_node,
        ],
        condition=IfCondition(LaunchConfiguration('remap_tf')),
    )

    joint_state_broadcaster_spawner = Node(
        package="controller_manager",
        namespace=LaunchConfiguration('name'),
        executable="spawner",
        arguments=["joint_state_broadcaster", "-c", "controller_manager"],
    )

    robot_controller_spawner = Node(
        package="controller_manager",
        namespace=LaunchConfiguration('name'),
        executable="spawner",
        arguments=["dsr_controller2", "-c", "controller_manager"],
    )

    nodes = [
        run_emulator_node,
        original_tf_nodes,
        remapped_tf_nodes,
        robot_controller_spawner,
        joint_state_broadcaster_spawner,
        control_node,
    ]

    return LaunchDescription(ARGUMENTS + nodes)
