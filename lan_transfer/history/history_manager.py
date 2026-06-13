import os
import json
import time
from typing import Dict, List, Optional
from datetime import datetime

from lan_transfer.config import HISTORY_FILE, DOWNLOAD_DIR


class HistoryRecord:
    def __init__(
        self,
        file_id: str,
        file_name: str,
        file_path: str,
        file_size: int,
        peer_ip: str,
        peer_name: str,
        direction: str,
        status: str,
        speed: float = 0,
        start_time: float = None,
        end_time: float = None,
        error: str = "",
    ):
        self.file_id = file_id
        self.file_name = file_name
        self.file_path = file_path
        self.file_size = file_size
        self.peer_ip = peer_ip
        self.peer_name = peer_name
        self.direction = direction
        self.status = status
        self.speed = speed
        self.start_time = start_time
        self.end_time = end_time
        self.error = error

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "peer_ip": self.peer_ip,
            "peer_name": self.peer_name,
            "direction": self.direction,
            "status": self.status,
            "speed": self.speed,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryRecord":
        return cls(
            file_id=data.get("file_id", ""),
            file_name=data.get("file_name", ""),
            file_path=data.get("file_path", ""),
            file_size=data.get("file_size", 0),
            peer_ip=data.get("peer_ip", ""),
            peer_name=data.get("peer_name", ""),
            direction=data.get("direction", ""),
            status=data.get("status", ""),
            speed=data.get("speed", 0),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            error=data.get("error", ""),
        )


class HistoryManager:
    def __init__(self):
        self.records: List[HistoryRecord] = []
        self.max_records = 500
        self._load()

    def _load(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.records = [HistoryRecord.from_dict(r) for r in data]
        except Exception as e:
            print(f"加载历史记录失败: {e}")
            self.records = []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                data = [r.to_dict() for r in self.records[-self.max_records:]]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史记录失败: {e}")

    def add_record(self, record: HistoryRecord):
        existing = next((r for r in self.records if r.file_id == record.file_id), None)
        if existing:
            idx = self.records.index(existing)
            self.records[idx] = record
        else:
            self.records.append(record)

        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

        self._save()

    def add_from_transfer_task(self, task, peer_name: str = ""):
        record = HistoryRecord(
            file_id=task.file_id,
            file_name=task.file_name,
            file_path=task.file_path,
            file_size=task.file_size,
            peer_ip=task.target_ip,
            peer_name=peer_name,
            direction=task.direction,
            status=task.status,
            speed=task.speed,
            start_time=task.start_time,
            end_time=task.end_time,
            error=task.error or "",
        )
        self.add_record(record)

    def update_record(self, file_id: str, **kwargs):
        for record in self.records:
            if record.file_id == file_id:
                for key, value in kwargs.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                self._save()
                return True
        return False

    def get_records(
        self,
        direction: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[HistoryRecord]:
        records = self.records.copy()

        if direction:
            records = [r for r in records if r.direction == direction]
        if status:
            records = [r for r in records if r.status == status]

        records.sort(key=lambda r: r.end_time or r.start_time or 0, reverse=True)

        if limit:
            records = records[:limit]

        return records

    def get_today_records(self) -> List[HistoryRecord]:
        today = datetime.now().date()
        return [
            r for r in self.records
            if r.end_time and datetime.fromtimestamp(r.end_time).date() == today
        ]

    def clear_history(self):
        self.records.clear()
        self._save()

    def delete_record(self, file_id: str) -> bool:
        for i, record in enumerate(self.records):
            if record.file_id == file_id:
                del self.records[i]
                self._save()
                return True
        return False

    def get_statistics(self) -> dict:
        total = len(self.records)
        completed = len([r for r in self.records if r.status == "completed"])
        failed = len([r for r in self.records if r.status in ["failed", "rejected", "cancelled"]])
        sent = len([r for r in self.records if r.direction == "send"])
        received = len([r for r in self.records if r.direction == "receive"])

        total_size_sent = sum(r.file_size for r in self.records if r.direction == "send" and r.status == "completed")
        total_size_received = sum(r.file_size for r in self.records if r.direction == "receive" and r.status == "completed")

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "sent": sent,
            "received": received,
            "total_size_sent": total_size_sent,
            "total_size_received": total_size_received,
        }
