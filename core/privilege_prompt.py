import queue
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApprovalRequest:
    title: str
    intro: str
    action_description: str
    details_html: str = ""
    approved: Optional[bool] = None
    event: threading.Event = field(default_factory=threading.Event)


class ApprovalBroker:
    def __init__(self):
        self._queue = queue.Queue()

    def submit_and_wait(self, request: ApprovalRequest) -> bool:
        self._queue.put(request)
        request.event.wait()
        return bool(request.approved)

    def get_next_request(self) -> Optional[ApprovalRequest]:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None


approval_broker = ApprovalBroker()
