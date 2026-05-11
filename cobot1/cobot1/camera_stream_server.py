#!/usr/bin/env python3
"""
==============================================================================
나만의 도련님 도시락 - USB 카메라 스트리밍 서버 (CCTV용)
==============================================================================
역할:
  - 내 PC에 연결된 USB 카메라 영상을 MJPEG 스트림으로 발행
  - 관리자 웹페이지의 <img> 태그가 이 URL 을 직접 src 로 사용
  - YOLO/별도 영상처리 없음 (순수 패스스루)

설치:
  pip install flask opencv-python

실행:
  python3 camera_stream_server.py
  
  또는 카메라 인덱스 / 포트 / 해상도 변경:
  python3 camera_stream_server.py --camera 0 --port 5000 --width 1280 --height 720

접속 (관리자 웹에서):
  http://<내PC_IP>:5000/video_feed
  
  내 PC IP 확인:
    Linux : ip addr  →  inet 192.168.x.x
    Windows: ipconfig
==============================================================================
"""

import argparse
import threading
import time

import cv2
from flask import Flask, Response, render_template_string

# ============================================================================
# 인자
# ============================================================================
parser = argparse.ArgumentParser()
parser.add_argument("--camera", type=int, default=0, help="USB 카메라 인덱스 (기본 2)")
parser.add_argument("--port", type=int, default=5000, help="HTTP 포트 (기본 5000)")
parser.add_argument("--width", type=int, default=1280, help="카메라 가로 해상도")
parser.add_argument("--height", type=int, default=720, help="카메라 세로 해상도")
parser.add_argument("--fps", type=int, default=20, help="목표 FPS")
parser.add_argument("--quality", type=int, default=70, help="JPEG 품질 1~100")
args = parser.parse_args()

# ============================================================================
# 카메라 캡처 클래스 (스레드로 항상 최신 프레임 유지)
# ============================================================================
class CameraCapture:
    """
    백그라운드 스레드에서 계속 카메라를 읽어서
    가장 최신 프레임만 메모리에 보관.
    여러 클라이언트가 접속해도 서로 영향 없음.
    """

    def __init__(self, cam_index, width, height):
        self.cam_index = cam_index
        print(f"[Camera] 카메라 인덱스 {cam_index} 열기...")
        self.cap = cv2.VideoCapture(cam_index)

        if not self.cap.isOpened():
            raise RuntimeError(f"카메라 인덱스 {cam_index} 를 열 수 없어요.")

        # 해상도 설정 (카메라가 지원하는 값으로 자동 조정됨)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[Camera] 해상도: {actual_w}x{actual_h}")

        self.frame = None
        self.lock = threading.Lock()
        self.running = True

        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("[Camera] 프레임 읽기 실패, 0.5초 후 재시도")
                time.sleep(0.5)
                continue

            with self.lock:
                self.frame = frame

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def release(self):
        self.running = False
        time.sleep(0.2)
        if self.cap:
            self.cap.release()


# ============================================================================
# Flask 앱
# ============================================================================
app = Flask(__name__)
camera = None


# ── HTML 미리보기 페이지 ──
PREVIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>📷 도련님 도시락 - 카메라 미리보기</title>
    <style>
        body {
            background: #0d1117; color: #c9d1d9;
            font-family: monospace; text-align: center;
            margin: 0; padding: 20px;
        }
        h1 { color: #58a6ff; }
        img {
            max-width: 100%; height: auto;
            border: 2px solid #30363d; border-radius: 8px;
        }
        .info {
            margin-top: 12px; color: #8b949e; font-size: 0.9em;
        }
        code { color: #f0883e; }
    </style>
</head>
<body>
    <h1>📷 USB 카메라 라이브 스트림</h1>
    <img src="/video_feed" alt="카메라 스트림">
    <div class="info">
        스트림 URL: <code>/video_feed</code><br>
        관리자 웹의 <code>&lt;img&gt;</code> 태그 src 에 이 주소를 넣으세요.
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    """브라우저에서 직접 열면 미리보기 페이지"""
    return render_template_string(PREVIEW_HTML)


def generate_mjpeg():
    """
    MJPEG 스트림 제너레이터.
    multipart/x-mixed-replace 형식으로 JPEG 프레임을 계속 push.
    """
    boundary = b"--frame"
    interval = 1.0 / max(args.fps, 1)

    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        # JPEG 인코딩
        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), args.quality]
        )
        if not ok:
            continue

        jpeg_bytes = buf.tobytes()

        yield (
            boundary + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
            + jpeg_bytes + b"\r\n"
        )
        time.sleep(interval)


@app.route("/video_feed")
def video_feed():
    """관리자 웹의 <img src="..."> 가 직접 사용하는 엔드포인트"""
    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/snapshot")
def snapshot():
    """단일 JPEG 프레임 (스냅샷 용도)"""
    frame = camera.get_frame()
    if frame is None:
        return "no frame", 503
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), args.quality])
    if not ok:
        return "encode failed", 500
    return Response(buf.tobytes(), mimetype="image/jpeg")


# ============================================================================
# main
# ============================================================================
def main():
    global camera

    print("=" * 60)
    print("  📷 도련님 도시락 - 카메라 스트리밍 서버")
    print("=" * 60)
    print(f"  카메라 인덱스 : {args.camera}")
    print(f"  해상도        : {args.width}x{args.height}")
    print(f"  목표 FPS      : {args.fps}")
    print(f"  JPEG 품질     : {args.quality}")
    print(f"  HTTP 포트     : {args.port}")
    print("=" * 60)

    try:
        camera = CameraCapture(args.camera, args.width, args.height)
    except RuntimeError as e:
        print(f"[오류] {e}")
        print("  → /dev/video* 를 확인하거나, --camera 인덱스를 1, 2 등으로 바꿔보세요.")
        return

    print()
    print(f"📺 미리보기 : http://localhost:{args.port}/")
    print(f"📡 스트림 URL: http://<내PC_IP>:{args.port}/video_feed")
    print(f"🛑 종료      : Ctrl+C")
    print()

    try:
        # threaded=True 로 여러 클라이언트 동시 접속 허용
        app.run(host="0.0.0.0", port=args.port, threaded=True, debug=False)
    except KeyboardInterrupt:
        print("\n[종료] 카메라 해제 중...")
    finally:
        if camera:
            camera.release()
        print("[종료] 완료")


if __name__ == "__main__":
    main()
