import os
import zipfile
import shutil
import threading
import tempfile
from typing import Callable, Optional, List

from lan_transfer.config import (
    DOWNLOAD_DIR,
    TEMP_DIR,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_TRANSFERRING,
)
from lan_transfer.transfer.file_transfer import FileTransfer, TransferTask
from lan_transfer.utils import generate_file_id


class FolderTransfer:
    def __init__(self, file_transfer: FileTransfer):
        self.file_transfer = file_transfer
        self.folder_tasks: dict = {}
        self._temp_files: dict = {}
        self._file_id_map: dict = {}
        self.callbacks = {
            "folder_started": [],
            "folder_progress": [],
            "folder_completed": [],
            "folder_failed": [],
        }

        self.file_transfer.register_callback("task_completed", self._on_file_completed)
        self.file_transfer.register_callback("task_failed", self._on_file_failed)
        self.file_transfer.register_callback("task_progress", self._on_file_progress)
        self.file_transfer.register_callback("task_started", self._on_file_started)

    def register_callback(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event].append(callback)

    def _trigger_event(self, event: str, *args, **kwargs):
        for callback in self.callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"Callback error for {event}: {e}")

    def is_folder(self, path: str) -> bool:
        return os.path.isdir(path)

    def send_folder(self, folder_path: str, target_ip: str) -> Optional[TransferTask]:
        if not os.path.isdir(folder_path):
            return None

        folder_name = os.path.basename(folder_path.rstrip(os.sep))
        zip_filename = f"{folder_name}.zip"
        temp_zip_path = os.path.join(TEMP_DIR, f"{generate_file_id()}_{zip_filename}")

        try:
            self._zip_folder(folder_path, temp_zip_path)
        except Exception as e:
            print(f"压缩文件夹失败: {e}")
            return None

        inner_task = self.file_transfer.send_file(temp_zip_path, target_ip)
        if not inner_task:
            try:
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
            except Exception:
                pass
            return None

        folder_file_id = generate_file_id()
        inner_task.is_compressed = True
        inner_task.original_name = folder_name
        inner_task._display_name = folder_name

        self._temp_files[inner_task.file_id] = temp_zip_path
        self._file_id_map[inner_task.file_id] = inner_task.file_id
        self.folder_tasks[inner_task.file_id] = {
            "temp_path": temp_zip_path,
            "is_folder": True,
            "original_name": folder_name,
        }

        self._trigger_event("folder_started", inner_task)

        return inner_task

    def send_paths(self, paths: List[str], target_ip: str) -> List[TransferTask]:
        tasks = []
        files = []
        folders = []

        for path in paths:
            if os.path.isdir(path):
                folders.append(path)
            elif os.path.isfile(path):
                files.append(path)

        for file_path in files:
            task = self.file_transfer.send_file(file_path, target_ip)
            if task:
                tasks.append(task)

        for folder_path in folders:
            task = self.send_folder(folder_path, target_ip)
            if task:
                tasks.append(task)

        return tasks

    def _zip_folder(self, folder_path: str, zip_path: str):
        folder_path = os.path.abspath(folder_path)
        folder_name = os.path.basename(folder_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.join(
                        folder_name, os.path.relpath(file_path, folder_path)
                    )
                    zipf.write(file_path, arcname)

    def _unzip_folder(self, zip_path: str, extract_to: str) -> str:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            namelist = zipf.namelist()
            if not namelist:
                raise Exception("ZIP文件为空")

            first_item = namelist[0]
            inner_folder_name = first_item.split("/")[0] if "/" in first_item else ""

            if inner_folder_name:
                safe_name = self._get_unique_name(extract_to, inner_folder_name)

                if safe_name == inner_folder_name:
                    zipf.extractall(extract_to)
                    return os.path.join(extract_to, inner_folder_name)
                else:
                    temp_extract_dir = tempfile.mkdtemp(dir=TEMP_DIR)
                    try:
                        zipf.extractall(temp_extract_dir)
                        src_path = os.path.join(temp_extract_dir, inner_folder_name)
                        dst_path = os.path.join(extract_to, safe_name)
                        if os.path.exists(src_path):
                            shutil.move(src_path, dst_path)
                            return dst_path
                        else:
                            for item in namelist:
                                item_path = os.path.join(temp_extract_dir, item)
                                if os.path.isfile(item_path):
                                    target_dir = os.path.dirname(
                                        os.path.join(extract_to, safe_name, item)
                                    )
                                    os.makedirs(target_dir, exist_ok=True)
                                    shutil.move(item_path, os.path.join(extract_to, safe_name, item))
                            return os.path.join(extract_to, safe_name)
                    finally:
                        try:
                            shutil.rmtree(temp_extract_dir)
                        except Exception:
                            pass
            else:
                safe_name = self._get_unique_name(extract_to, "extracted_folder")
                dst_path = os.path.join(extract_to, safe_name)
                os.makedirs(dst_path, exist_ok=True)
                zipf.extractall(dst_path)
                return dst_path

    def _get_unique_name(self, base_dir: str, name: str) -> str:
        if not os.path.exists(os.path.join(base_dir, name)):
            return name

        base, ext = os.path.splitext(name)
        counter = 1
        while True:
            new_name = f"{base}_{counter}{ext}"
            if not os.path.exists(os.path.join(base_dir, new_name)):
                return new_name
            counter += 1

    def _on_file_started(self, task: TransferTask):
        if task.file_id in self.folder_tasks:
            self._trigger_event("folder_started", task)

    def _on_file_completed(self, task: TransferTask):
        if task.file_id in self.folder_tasks:
            if task.direction == "receive" and task.file_name.endswith(".zip"):
                try:
                    extracted_path = self._unzip_folder(task.file_path, DOWNLOAD_DIR)

                    try:
                        if os.path.exists(task.file_path):
                            os.remove(task.file_path)
                    except Exception:
                        pass

                    task.file_path = extracted_path
                    task.file_name = os.path.basename(extracted_path)
                    task.is_compressed = False
                    task.original_name = task.file_name

                except Exception as e:
                    print(f"解压文件夹失败: {e}")

            self._trigger_event("folder_completed", task)
            self._cleanup_temp(task.file_id)

    def _on_file_failed(self, task: TransferTask):
        if task.file_id in self.folder_tasks:
            self._trigger_event("folder_failed", task)
            self._cleanup_temp(task.file_id)

    def _on_file_progress(self, task: TransferTask):
        if task.file_id in self.folder_tasks:
            self._trigger_event("folder_progress", task)

    def _cleanup_temp(self, file_id: str):
        if file_id in self._temp_files:
            temp_path = self._temp_files[file_id]
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                print(f"删除临时文件失败: {e}")
            del self._temp_files[file_id]

        if file_id in self.folder_tasks:
            del self.folder_tasks[file_id]

        if file_id in self._file_id_map:
            del self._file_id_map[file_id]

    def cleanup_all_temp(self):
        for file_id in list(self._temp_files.keys()):
            self._cleanup_temp(file_id)
