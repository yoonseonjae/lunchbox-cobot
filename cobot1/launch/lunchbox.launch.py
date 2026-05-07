from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='cobot1',
            executable='lunchbox_robot_node',
            name='lunchbox_robot_node',
            namespace='dsr01',
            output='screen',
        ),
    ])
