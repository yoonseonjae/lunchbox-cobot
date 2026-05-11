from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'cobot1'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    # ── 데이터 파일 ──────────────────────────────────────────────
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # launch 파일
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
        # 좌표 YAML 설정 파일 (패키지 루트 config/)
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
        # Firebase 키 (gitignore 필수)
        (os.path.join('share', package_name, 'config'),
            glob('config/*.json')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yoon',
    maintainer_email='yoon@todo.com',
    description='나만의 도련님 도시락 - M0609 로봇 제어 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    # ── 실행 진입점 ──────────────────────────────────────────────
    entry_points={
        'console_scripts': [
            'lunchbox_robot_node = cobot1.lunchbox_robot_node:main',
            'lunchbox_database_node = cobot1.lunchbox_database_node:main',
            'robot_dashboard     = cobot1.robot_dashboard:main',
            'camera_stream_server     = cobot1.camera_stream_server:main',
            'mini_jog                 = cobot1.mini_jog:main',
            'move_basic               = cobot1.move_basic:main',
        ],
    },
)