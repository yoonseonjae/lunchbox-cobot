cmake_minimum_required(VERSION 3.8)
project(m0609_rg2_combined)

find_package(ament_cmake REQUIRED)

# Install URDF files
install(FILES
  m0609_rg2.urdf
  m0609_rg2_rviz.urdf
  DESTINATION share/${PROJECT_NAME}
)

# Install mesh directories
install(DIRECTORY meshes/
  DESTINATION share/${PROJECT_NAME}/meshes
)

# Install launch files
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install rviz config
install(DIRECTORY rviz/
  DESTINATION share/${PROJECT_NAME}/rviz
)

ament_package()
