import os
import time
import threading
import json
from typing import Dict, Callable, Optional, List

from lan_transfer.config import (
    BUFFER_SIZE,
    DOWNLOAD_DIR,
    TEMP_DIR,
    MSG_TYPE_FILE_REQUEST,
    MSG_TYPE_FILE_RESPONSE,
    MSG_TYPE_FILE_CHUNK,
    MSG_TYPE_FILE_COMPLETE,
    MSG_TYPE_RESUME_REQUEST,
    MSG_TYPE_RESUME_RESPONSE,
    STATUS_PENDING,
    STATUS_TRANSFERRING,
    STATUS_COMPLETED,
    STATUS_REJECTED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)
from lan_transfer.utils import generate_file_id, get_md5
from lan_transfer.network.connection import ConnectionManager


class TransferTask:
    def __init__(
        self,
        file_id: str,
        file_path: str,
        file_name: str,
        file_size: int,
        target_ip: str,
        direction: str = "send",
        is_compressed: bool = False,
        original_name: str = "",
    ):
        self.file_id = file_id
        self.file_path = file_path
        self.file_name = file_name
        self.file_size = file_size
        self.target_ip = target_ip
        self.direction = direction
        self.is_compressed = is_compressed
        self.original_name = original_name
        self.status = STATUS_PENDING
        self.transferred = 0
        self.start_time = None
        self.end_time = None
        self.speed = 0
        self.md5 = None
        self.error = None
        self._cancel_flag = threading.Event()
        self._pause_flag = threading.Event()

    def cancel(self):
        self._cancel_flag.set()

    def is_cancelled(self):
        return self._cancel_flag.is_set()

    def get_progress(self) -> float:
        if self.file_size == 0:
            return 100.0
        return (self.transferred / self.file_size) * 100

    def get_elapsed_time(self) -> float:
        if self.start_time is None:
            return 0
        end = self.end_time or time.time()
        return end - self.start_time

    def get_eta(self) -> float:
        if self.speed <= 0 or self.file_size == 0:
            return 0
        remaining = self.file_size - self.transferred
        return remaining / self.speed


class FileTransfer:
    def __init__(self, connection_manager: ConnectionManager):
        self.conn_manager = connection_manager
        self.tasks: Dict[str, TransferTask] = {}
        self.pending_requests: Dict[str, dict] = {}
        self.connection_keys: Dict[str, str] = {}
        self.callbacks = {
            "task_started": [],
            "task_progress": [],
            "task_completed": [],
            "task_failed": [],
            "file_request": [],
        }
        self._lock = threading.Lock()

        self.conn_manager.register_callback("file_request", self._handle_file_message)

    def register_callback(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event].append(callback)

    def _trigger_event(self, event: str, *args, **kwargs):
        for callback in self.callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"Callback error for {event}: {e}")

    def _handle_file_message(self, ip: str, msg: dict):
        msg_type = msg.get("type")
        if msg_type == MSG_TYPE_FILE_REQUEST:
            self._handle_file_request(ip, msg)
        elif msg_type == MSG_TYPE_FILE_RESPONSE:
            self._handle_file_response(ip, msg)
        elif msg_type == MSG_TYPE_FILE_CHUNK:
            pass
        elif msg_type == MSG_TYPE_FILE_COMPLETE:
            self._handle_file_complete(ip, msg)
        elif msg_type == MSG_TYPE_RESUME_REQUEST:
            self._handle_resume_request(ip, msg)
        elif msg_type == MSG_TYPE_RESUME_RESPONSE:
            self._handle_resume_response(ip, msg)

    def send_file(self, file_path: str, target_ip: str) -> Optional[TransferTask]:
        if not os.path.exists(file_path):
            return None

        file_id = generate_file_id()
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        file_md5 = get_md5(file_path)

        task = TransferTask(
            file_id=file_id,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            target_ip=target_ip,
            direction="send",
        )
        task.md5 = file_md5

        with self._lock:
            self.tasks[file_id] = task

        request_msg = {
            "type": MSG_TYPE_FILE_REQUEST,
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "file_md5": file_md5,
        }

        if self.conn_manager.send_file_message(target_ip, request_msg):
            return task
        else:
            task.status = STATUS_FAILED
            task.error = "无法连接到目标设备"
            self._trigger_event("task_failed", task)
            return None

    def send_files(self, file_paths: List[str], target_ip: str) -> List[TransferTask]:
        tasks = []
        for file_path in file_paths:
            task = self.send_file(file_path, target_ip)
            if task:
                tasks.append(task)
        return tasks

    def _handle_file_request(self, ip: str, msg: dict):
        file_id = msg.get("file_id")
        file_name = msg.get("file_name")
        file_size = msg.get("file_size")
        file_md5 = msg.get("file_md5")
        connection_key = msg.get("_connection_key")

        if not file_id:
            return

        if connection_key:
            self.connection_keys[file_id] = connection_key

        temp_file = os.path.join(TEMP_DIR, f"{file_id}.part")
        existing_size = os.path.getsize(temp_file) if os.path.exists(temp_file) else 0

        if existing_size > 0 and existing_size < file_size:
            resume_msg = {
                "type": MSG_TYPE_RESUME_REQUEST,
                "file_id": file_id,
                "file_name": file_name,
                "file_size": file_size,
                "existing_size": existing_size,
            }
            self.conn_manager.send_file_message(ip, resume_msg)
            return

        task = TransferTask(
            file_id=file_id,
            file_path=os.path.join(DOWNLOAD_DIR, file_name),
            file_name=file_name,
            file_size=file_size,
            target_ip=ip,
            direction="receive",
        )
        task.md5 = file_md5

        with self._lock:
            self.tasks[file_id] = task

        self.pending_requests[file_id] = {
            "ip": ip,
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "file_md5": file_md5,
            "task": task,
            "connection_key": connection_key,
        }

        self._trigger_event("file_request", ip, msg)

    def accept_file(self, file_id: str):
        if file_id not in self.pending_requests:
            return False

        req = self.pending_requests[file_id]
        task = req["task"]
        task.status = STATUS_TRANSFERRING
        task.start_time = time.time()

        connection_key = req.get("connection_key")
        conn = None
        if connection_key:
            conn = self.conn_manager.get_receive_connection(connection_key)
            self.conn_manager._trigger_event("start_receiving")

        response_msg = {
            "type": MSG_TYPE_FILE_RESPONSE,
            "file_id": file_id,
            "accepted": True,
        }

        if self.conn_manager.send_file_message(req["ip"], response_msg):
            threading.Thread(
                target=self._receive_file,
                args=(task, req["ip"], 0, conn, connection_key),
                daemon=True,
            ).start()
            self._trigger_event("task_started", task)
            del self.pending_requests[file_id]
            return True
        return False

    def reject_file(self, file_id: str):
        if file_id not in self.pending_requests:
            return False

        req = self.pending_requests[file_id]
        task = req["task"]
        task.status = STATUS_REJECTED

        response_msg = {
            "type": MSG_TYPE_FILE_RESPONSE,
            "file_id": file_id,
            "accepted": False,
        }

        self.conn_manager.send_file_message(req["ip"], response_msg)
        self._trigger_event("task_failed", task)
        del self.pending_requests[file_id]

        with self._lock:
            if file_id in self.tasks:
                del self.tasks[file_id]

        return True

    def _handle_file_response(self, ip: str, msg: dict):
        file_id = msg.get("file_id")
        accepted = msg.get("accepted", False)

        with self._lock:
            task = self.tasks.get(file_id)

        if not task:
            return

        if not accepted:
            task.status = STATUS_REJECTED
            self._trigger_event("task_failed", task)
            return

        task.status = STATUS_TRANSFERRING
        task.start_time = time.time()
        self._trigger_event("task_started", task)

        threading.Thread(
            target=self._send_file,
            args=(task, ip, 0),
            daemon=True,
        ).start()

    def _handle_resume_request(self, ip: str, msg: dict):
        file_id = msg.get("file_id")
        existing_size = msg.get("existing_size", 0)

        with self._lock:
            task = self.tasks.get(file_id)

        if not task or task.direction != "send":
            return

        temp_file = os.path.join(TEMP_DIR, f"{file_id}.part")
        if os.path.exists(temp_file):
            os.remove(temp_file)

        task.transferred = existing_size
        task.status = STATUS_TRANSFERRING
        task.start_time = time.time()

        response_msg = {
            "type": MSG_TYPE_RESUME_RESPONSE,
            "file_id": file_id,
            "can_resume": True,
            "resume_offset": existing_size,
        }
        self.conn_manager.send_file_message(ip, response_msg)

        self._trigger_event("task_started", task)

        threading.Thread(
            target=self._send_file,
            args=(task, ip, existing_size),
            daemon=True,
        ).start()

    def _handle_resume_response(self, ip: str, msg: dict):
        file_id = msg.get("file_id")
        can_resume = msg.get("can_resume", False)
        resume_offset = msg.get("resume_offset", 0)

        if file_id not in self.pending_requests:
            return

        req = self.pending_requests[file_id]
        task = req["task"]

        connection_key = req.get("connection_key")
        conn = None
        if connection_key:
            conn = self.conn_manager.get_receive_connection(connection_key)
            self.conn_manager._trigger_event("start_receiving")

        if not can_resume:
            temp_file = os.path.join(TEMP_DIR, f"{file_id}.part")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            task.transferred = 0

        task.status = STATUS_TRANSFERRING
        task.start_time = time.time()
        task.transferred = resume_offset

        response_msg = {
            "type": MSG_TYPE_FILE_RESPONSE,
            "file_id": file_id,
            "accepted": True,
            "resume": True,
            "resume_offset": resume_offset,
        }
        self.conn_manager.send_file_message(ip, response_msg)

        threading.Thread(
            target=self._receive_file,
            args=(task, ip, resume_offset, conn, connection_key),
            daemon=True,
        ).start()
        self._trigger_event("task_started", task)
        del self.pending_requests[file_id]

    def _send_file(self, task: TransferTask, target_ip: str, start_offset: int = 0):
        chunk_size = BUFFER_SIZE * 16
        last_update = time.time()
        bytes_since_update = 0

        try:
            with open(task.file_path, "rb") as f:
                f.seek(start_offset)
                task.transferred = start_offset

                while task.transferred < task.file_size:
                    if task.is_cancelled():
                        task.status = STATUS_CANCELLED
                        self._trigger_event("task_failed", task)
                        return

                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    metadata = {
                        "type": MSG_TYPE_FILE_CHUNK,
                        "file_id": task.file_id,
                        "offset": task.transferred,
                        "length": len(chunk),
                    }

                    if not self.conn_manager.send_file_chunk(target_ip, chunk, metadata):
                        raise Exception("发送数据块失败")

                    task.transferred += len(chunk)
                    bytes_since_update += len(chunk)

                    now = time.time()
                    if now - last_update >= 0.5:
                        elapsed = now - last_update
                        task.speed = bytes_since_update / elapsed if elapsed > 0 else 0
                        bytes_since_update = 0
                        last_update = now
                        self._trigger_event("task_progress", task)

            complete_msg = {
                "type": MSG_TYPE_FILE_COMPLETE,
                "file_id": task.file_id,
                "success": True,
            }
            self.conn_manager.send_file_message(target_ip, complete_msg)

            task.status = STATUS_COMPLETED
            task.end_time = time.time()
            self._trigger_event("task_progress", task)
            self._trigger_event("task_completed", task)

        except Exception as e:
            task.status = STATUS_FAILED
            task.error = str(e)
            self._trigger_event("task_failed", task)

    def _receive_file(self, task: TransferTask, source_ip: str, start_offset: int = 0, conn=None, connection_key=None):
        temp_file = os.path.join(TEMP_DIR, f"{task.file_id}.part")
        final_file = task.file_path
        last_update = time.time()
        bytes_since_update = 0

        try:
            mode = "ab" if start_offset > 0 else "wb"
            with open(temp_file, mode) as f:
                task.transferred = start_offset

                while task.transferred < task.file_size:
                    if task.is_cancelled():
                        task.status = STATUS_CANCELLED
                        self._trigger_event("task_failed", task)
                        return

                    if conn is None:
                        conn = self.conn_manager.file_connections.get(source_ip)
                    if conn is None:
                        raise Exception("连接已断开")

                    metadata, chunk = self.conn_manager.receive_file_chunk(conn)

                    if metadata is None or chunk is None:
                        raise Exception("接收数据块失败")

                    if metadata.get("type") == MSG_TYPE_FILE_COMPLETE:
                        break

                    f.write(chunk)
                    task.transferred += len(chunk)
                    bytes_since_update += len(chunk)

                    now = time.time()
                    if now - last_update >= 0.5:
                        elapsed = now - last_update
                        task.speed = bytes_since_update / elapsed if elapsed > 0 else 0
                        bytes_since_update = 0
                        last_update = now
                        self._trigger_event("task_progress", task)

            import shutil
            os.makedirs(os.path.dirname(final_file), exist_ok=True)
            shutil.move(temp_file, final_file)

            if task.md5:
                received_md5 = get_md5(final_file)
                if received_md5 and received_md5 != task.md5:
                    raise Exception("文件校验失败，MD5不匹配")

            task.status = STATUS_COMPLETED
            task.end_time = time.time()
            self._trigger_event("task_progress", task)
            self._trigger_event("task_completed", task)

        except Exception as e:
            task.status = STATUS_FAILED
            task.error = str(e)
            self._trigger_event("task_failed", task)
        finally:
            if os.path.exists(temp_file) and task.status == STATUS_COMPLETED:
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

            if connection_key and conn is not None:
                try:
                    self.conn_manager.release_receive_connection(connection_key)
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            if task.file_id in self.connection_keys:
                del self.connection_keys[task.file_id]

    def _handle_file_complete(self, ip: str, msg: dict):
        file_id = msg.get("file_id")
        success = msg.get("success", False)

        with self._lock:
            task = self.tasks.get(file_id)

        if task and success:
            task.status = STATUS_COMPLETED
            task.end_time = time.time()
            self._trigger_event("task_completed", task)

    def cancel_task(self, file_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(file_id)
        if task:
            task.cancel()
            return True
        return False

    def get_tasks(self) -> List[TransferTask]:
        with self._lock:
            return list(self.tasks.values())

    def get_task(self, file_id: str) -> Optional[TransferTask]:
        with self._lock:
            return self.tasks.get(file_id)

    def cleanup_completed_tasks(self):
        with self._lock:
            to_remove = [
                fid for fid, task in self.tasks.items()
                if task.status in [STATUS_COMPLETED, STATUS_FAILED, STATUS_REJECTED, STATUS_CANCELLED]
            ]
            for fid in to_remove:
                del self.tasks[fid]
