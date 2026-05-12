from setuptools import find_packages, setup

package_name = 'lunchbox_web'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/web', ['admin_index.html']),
    ],
    install_requires=['setuptools', 'firebase-admin', 'aiohttp', 'flask', 'opencv-python'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='user@todo.todo',
    description='Lunchbox Web GUI package',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'user_order_app        = lunchbox_web.user_order_app:main',
            'robot_dashboard       = lunchbox_web.robot_dashboard:main',
            'mini_jog              = lunchbox_web.mini_jog:main',
            'move_basic            = lunchbox_web.move_basic:main',
        ],
    },
)
