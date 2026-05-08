#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os
from datetime import datetime  # 추가된 부분: 시간 객체 처리를 위해 필요

# --- 추가된 부분: 시간을 JSON 문자열로 바꿔주는 마법의 번역기 ---
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        # 만약 데이터가 시간(datetime) 객체라면, 일반 문자열(ISO 포맷)로 변환
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)
# -----------------------------------------------------------

class FirebaseBridgeNode(Node):
    def __init__(self):
        super().__init__('firebase_bridge_node')
        
        # 1. ROS 2 Publisher 설정 (실제 로봇 제어 노드가 구독할 토픽)
        self.order_pub = self.create_publisher(String, 'robot_order', 10)

        # 💡 로봇의 상태 보고를 듣는 귀(Subscriber) 추가
        self.status_sub = self.create_subscription(String, '/order_status', self.status_callback, 10)
        
        # 2. Firebase 초기화 (새 프로젝트 인증키 적용 완료)
        key_path = os.path.expanduser(
          "~/cobot_ws/cobot1/config/rokey-d3991-firebase-adminsdk-fbsvc-196a3c21f2.json"
        )
        
        try:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self.get_logger().info('✅ Firebase Admin SDK 초기화 성공!')
        except Exception as e:
            self.get_logger().error(f'❌ Firebase 초기화 실패: {e}')
            return

        self.listen_to_orders()

    def listen_to_orders(self):
        from google.cloud.firestore_v1.base_query import FieldFilter
        order_query = self.db.collection('orders').where(filter=FieldFilter('status', '==', 'pending'))

        
        def on_snapshot(col_snapshot, changes, read_time):
            for change in changes:
                if change.type.name == 'ADDED':  
                    doc_id = change.document.id
                    order_info = change.document.to_dict()
                    
                    # 1. 주문 데이터에서 items 리스트 가져오기
                    items = order_info.get('items', [])
                    
                    # 2. 로봇이 기다리고 있는 빈 도시락통(변수) 준비
                    sub_dishes = []
                    main_dish = ""
                    
                    # 3. 가격/개수는 무시하고 '이름(name)'만 쏙쏙 뽑아 담기
                    for item in items:
                        name = item.get('name', '')
                        if name in ['김치', '단무지', '피클', '샐러드']:
                            sub_dishes.append(name)
                        elif name:
                            # 서브 반찬 3종이 아니면 메인 반찬으로 분류
                            main_dish = name
                            
                    self.get_logger().info(f'🔔 새 주문 접수! [ID: {doc_id}]')
                    self.get_logger().info(f'📦 분류 완료: 메인({main_dish}), 서브({sub_dishes})') 
                    
                    # 4. 로봇 입맛에 딱 맞게 최종 포장 (다른 군더더기 없음!)
                    order_payload = {
                        '_key': doc_id,
                        'sub_dishes': sub_dishes,
                        'main_dish': main_dish
                    }
                    
                    # 5. 시간 데이터가 빠졌으므로 일반 json.dumps로 깔끔하게 전송
                    msg = String()
                    msg.data = json.dumps(order_payload, ensure_ascii=False)
                    self.order_pub.publish(msg)

                    # 중복 처리 방지를 위해 즉시 'cooking'으로 업데이트
                    self.update_status(doc_id, 'cooking')
        


        # def on_snapshot(col_snapshot, changes, read_time):
        #     for change in changes:
        #         if change.type.name == 'ADDED':  
        #             doc_id = change.document.id
        #             order_info = change.document.to_dict()
                    
        #             items = order_info.get('items', [])
        #             item_names = ", ".join([item.get('name', '알 수 없는 메뉴') for item in items])
                    
        #             self.get_logger().info(f'🔔 새 주문 접수! [ID: {doc_id}]')
        #             self.get_logger().info(f'📦 주문 내용: {item_names}') 
                    
        #             msg = String()
        #             order_payload = order_info.copy()
        #             order_payload['_key'] = doc_id
                    
        #             # --- 수정된 부분: cls=CustomJSONEncoder 를 추가하여 시간 에러 방지 ---
        #             msg.data = json.dumps(order_payload, cls=CustomJSONEncoder, ensure_ascii=False)
        #             self.order_pub.publish(msg)

        #             self.update_status(doc_id, 'cooking')

        order_query.on_snapshot(on_snapshot)
        self.get_logger().info('🚀 Firestore 감시 모드 작동 중...')

    def update_status(self, doc_id, new_status):
        doc_ref = self.db.collection('orders').document(doc_id)
        doc_ref.update({'status': new_status})
        self.get_logger().info(f'📝 주문 {doc_id} 상태 업데이트: {new_status}')
    
    def status_callback(self, msg):
        try:
            data = json.loads(msg.data)
            doc_id = data.get('_key')
            new_status = data.get('status')
            
            if doc_id and new_status:
                self.get_logger().info(f"📡 로봇으로부터 상태 수신: {doc_id} -> {new_status}")
                self.update_status(doc_id, new_status)
                
        except Exception as e:
            self.get_logger().error(f"❌ 상태 보고 파싱 오류: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = FirebaseBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

# import rclpy
# from rclpy.node import Node
# from std_msgs.msg import String
# import firebase_admin
# from firebase_admin import credentials, firestore
# import json
# import os

# class FirebaseBridgeNode(Node):
#     def __init__(self):
#         super().__init__('firebase_bridge_node')
        
#         # 1. ROS 2 Publisher 설정 (실제 로봇 제어 노드가 구독할 토픽)
#         self.order_pub = self.create_publisher(String, 'robot_order', 10)
        
#         # 2. Firebase 초기화
#         # 성욱님이 알려주신 실제 경로를 사용합니다.
#         # key_path = os.path.expanduser('~/cobot_ws/src/firebase_ros2_controller/resource/rokey2-e9270-firebase-adminsdk-fbsvc-9f7d4aac47.json')
#         key_path = os.path.expanduser(
#                "~/cobot_ws/src/firebase_ros2_controller/resource/serviceAccountKey.json"
#         )
        
#         try:
#             cred = credentials.Certificate(key_path)
#             firebase_admin.initialize_app(cred)
#             self.db = firestore.client()
#             self.get_logger().info('✅ Firebase Admin SDK 초기화 성공!')
#         except Exception as e:
#             self.get_logger().error(f'❌ Firebase 초기화 실패: {e}')
#             return

#         # 3. Firestore 실시간 리스너 실행
#         self.listen_to_orders()

#     def listen_to_orders(self):
#         # 'status'가 'pending'인 주문만 필터링해서 감시
#         from google.cloud.firestore_v1.base_query import FieldFilter
#         order_query = self.db.collection('orders').where(filter=FieldFilter('status', '==', 'pending'))

#         def on_snapshot(col_snapshot, changes, read_time):
#             for change in changes:
#                 if change.type.name == 'ADDED':  # 새로운 주문이 추가되었을 때
#                     doc_id = change.document.id
#                     order_info = change.document.to_dict()
                    
#                     # 1. 주문 아이템 리스트에서 메뉴 이름들만 추출
#                     # Firestore 데이터 구조에 맞게 items 내의 name을 가져옵니다.
#                     items = order_info.get('items', [])
#                     item_names = ", ".join([item.get('name', '알 수 없는 메뉴') for item in items])
                    
#                     # 2. 로그에 메뉴 이름 포함하여 출력
#                     self.get_logger().info(f'🔔 새 주문 접수! [ID: {doc_id}]')
#                     self.get_logger().info(f'📦 주문 내용: {item_names}') # 이 줄을 추가    
                    
#                     # 로봇 제어 노드에 전달할 메시지 발행
#                     msg = String()
#                     msg.data = json.dumps({
#                         'id': doc_id,
#                         'items': order_info.get('items', []),
#                         'user': order_info.get('user_name', '고객')
#                     })
#                     self.order_pub.publish(msg)

#                     # 중요: 중복 실행 방지를 위해 상태를 'cooking'으로 즉시 변경
#                     self.update_status(doc_id, 'cooking')

#         # 리스너 등록
#         order_query.on_snapshot(on_snapshot)
#         self.get_logger().info('🚀 Firestore 감시 모드 작동 중...')

#     def update_status(self, doc_id, new_status):
#         doc_ref = self.db.collection('orders').document(doc_id)
#         doc_ref.update({'status': new_status})
#         self.get_logger().info(f'📝 주문 {doc_id} 상태 업데이트: {new_status}')

# def main(args=None):
#     rclpy.init(args=args)
#     node = FirebaseBridgeNode()
#     try:
#         rclpy.spin(node)
#     except KeyboardInterrupt:
#         pass
#     finally:
#         node.destroy_node()
#         rclpy.shutdown()

# if __name__ == '__main__':
#     main()