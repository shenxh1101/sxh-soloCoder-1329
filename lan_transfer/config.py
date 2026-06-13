import os
import socket


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_hostname():
    return socket.gethostname()


APP_NAME = "局域网文件传输工具"
APP_VERSION = "1.0.0"

LOCAL_IP = get_local_ip()
HOSTNAME = get_hostname()

UDP_DISCOVERY_PORT = 9999
TCP_FILE_PORT = 10000
TCP_CHAT_PORT = 10001

DISCOVERY_INTERVAL = 5
DEVICE_TIMEOUT = 15

BUFFER_SIZE = 4096
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "LanTransfer")
TEMP_DIR = os.path.join(DOWNLOAD_DIR, ".temp")
HISTORY_FILE = os.path.join(DOWNLOAD_DIR, ".history.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

MSG_TYPE_HELLO = "HELLO"
MSG_TYPE_BYE = "BYE"
MSG_TYPE_FILE_REQUEST = "FILE_REQUEST"
MSG_TYPE_FILE_RESPONSE = "FILE_RESPONSE"
MSG_TYPE_FILE_CHUNK = "FILE_CHUNK"
MSG_TYPE_FILE_COMPLETE = "FILE_COMPLETE"
MSG_TYPE_CHAT = "CHAT"
MSG_TYPE_RESUME_REQUEST = "RESUME_REQUEST"
MSG_TYPE_RESUME_RESPONSE = "RESUME_RESPONSE"

STATUS_PENDING = "pending"
STATUS_TRANSFERRING = "transferring"
STATUS_COMPLETED = "completed"
STATUS_PAUSED = "paused"
STATUS_CANCELLED = "cancelled"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
