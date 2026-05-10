import rclpy
import DR_init
import time

# 로봇 설정 상수 (필요에 따라 수정)
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
ROBOT_TOOL = "Tool Weight"
ROBOT_TCP = "GripperDA_v1"

# 이동 속도 및 가속도 (필요에 따라 수정)
VELOCITY = 40
ACC = 60
ON, OFF = 1, 0

# DR_init 설정
DR_init.__dsr__id = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL


def initialize_robot():
    """로봇의 Tool과 TCP를 설정"""
    from DSR_ROBOT2 import set_tool, set_tcp,get_tool,get_tcp,ROBOT_MODE_MANUAL,ROBOT_MODE_AUTONOMOUS  # 필요한 기능만 임포트
    from DSR_ROBOT2 import get_robot_mode,set_robot_mode

    # Tool과 TCP 설정시 매뉴얼 모드로 변경해서 진행
    set_robot_mode(ROBOT_MODE_MANUAL)
    set_tool(ROBOT_TOOL)
    set_tcp(ROBOT_TCP)
    
    set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    time.sleep(2)  # 설정 안정화를 위해 잠시 대기
    # 설정된 상수 출력
    print("#" * 50)
    print("Initializing robot with the following settings:")
    print(f"ROBOT_ID: {ROBOT_ID}")
    print(f"ROBOT_MODEL: {ROBOT_MODEL}")
    print(f"ROBOT_TCP: {get_tcp()}") 
    print(f"ROBOT_TOOL: {get_tool()}")
    print(f"ROBOT_MODE 0:수동, 1:자동 : {get_robot_mode()}")
    print(f"VELOCITY: {VELOCITY}")
    print(f"ACC: {ACC}")
    print("#" * 50)



def perform_task():
    """로봇이 수행할 작업"""
    print("Performing task...")
    from DSR_ROBOT2 import (
        posx,
        movej,
        movel,
        set_ref_coord,
        wait,
        movec,
        DR_MV_MOD_REL,
        DR_TOOL,
            DR_BASE,
        set_digital_output,
        get_digital_input,
        set_tool, 
        move_periodic,
    )  # 필요한 기능만 임포트

    def release():
        set_digital_output(3, ON)
        set_digital_output(1, OFF)
        set_digital_output(2, OFF)

    def grip():
        release()
        set_digital_output(3, OFF)
        set_digital_output(1, ON)
        set_digital_output(2, OFF)
    set_tool(ROBOT_TOOL)
    # 초기 위치 및 목표 위치 설정
    JReady = [0, 0, 90, 0, 90, 0]
    grip() 
    wait(5)
    release()
    # pos1 = posx([ 311.51, -354.31,  141.72,   86.77, -172.62,   83.96])
    pos_list = {
    "above_l":      [309.241, -311.564, 130.068, 92.607, -154.846, 87.949],
    "scoop_1_l":    [ 311.51, -354.31,  141.72,   86.77, -172.62,   83.96],
    "scoop_2_l":    [ 311.14, -338.28,  261.99,   88.09, -172.48,   85.48],
    "scoop_3_l_o":    [ 302.95, -338.31,  145.90,   95.49, -123.36,   84.43],
    # "scoop_3_l":    [307.43, -385.358, 146.337, 95.445, -123.317, 84.397],
    "scoop_4_l_o":    [ 308.50, -404.91,  100.07,   92.29, -127.87,   86.09],
    # "scoop_4_l":    [311.114, -404.799, 99.249, 83.18, -127.918, 88.992],
    "scoop_5_l":    [ 306.90, -409.71,  129.17,   93.64, -125.28,   88.12],
    "scoop_6_l":    [ 295.93, -356.23,  199.44,   97.32, -115.74,   86.84],
    # "periodic": [-11.337, -7.675, 128.77, -75.205, 62.179, 20.024],
    "transit_l":    [ 592.95,  -79.20,  401.79,  174.74, -101.29,   97.38],
    "place_pre_l":  [ 436.92, -150.80,  182.15,   65.42,  117.41,  -99.45],
    "place_down_l": [ 429.96, -151.37,  186.05,   65.71,  119.63,  131.19],
    "place_up_l":   [303.594, -315.467, 260.528, 97.708, -160.721, 86.117],
    "back_l":       [307.624, -319.38, 140.02, 89.068, -160.029, 85.007],
    "back_lean_l":  [309.241, -311.564, 130.068, 92.607, -154.846, 87.949],
    "home_ready_l": [ 480.22, -221.15,  277.26,  125.91, -168.25,   40.68]
    }

    # 반복 동작 수행
    while True:       
        # 이동 명령 실행
        print("movej")
        movej(JReady, vel=VELOCITY, acc=ACC)
        print("movel")
        # movel(pos1, vel=VELOCITY, acc=ACC)
        release()
        
        for name, pos in pos_list.items():
            print(f"Moving to {name}...")
            if name not in  [ "scoop_5_l", "scoop_6_l", "periodic"]:
                movel(pos, vel=VELOCITY, acc=ACC)
            wait(1)  # 각 위치에서 1초 대기
            if name in ["periodic"]:
                move_periodic(amp =[0,5,20,0,0,8], period=0.5, atime=0.2, repeat=10, ref=DR_TOOL)
                wait(1)
                move_periodic(amp =[0,5,20,0,0,8], period=1.0, atime=0.2, repeat=15, ref=DR_TOOL)
            if name in ["above_l"]:
                grip()
                wait(2)  # 각 위치에서 1초 대기
            if name in  ["scoop_5_l"]:
                movec(pos_list["scoop_5_l"], pos_list["scoop_6_l"], vel=VELOCITY, acc=ACC, radius=50)
            if name in  ["back_lean_l"]:
                release()
        # print("movec")        
        # movec(pos2, pos3, vel=VELOCITY, acc=ACC, )
    

def main(args=None):
    """메인 함수: ROS2 노드 초기화 및 동작 수행"""
    rclpy.init(args=args)
    node = rclpy.create_node("move_basic", namespace=ROBOT_ID)

    # DR_init에 노드 설정
    DR_init.__dsr__node = node

    try:
        # 초기화는 한 번만 수행
        initialize_robot()

        # 작업 수행 (한 번만 호출)
        perform_task()

    except KeyboardInterrupt:
        print("\nNode interrupted by user. Shutting down...")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()