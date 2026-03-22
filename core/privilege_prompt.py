import queue
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

APPROVAL_MASCOT_PATH = os.path.abspath("ui/media/mascot_art/can_i.png")


@dataclass
class ApprovalRequest:
    title: str
    intro: str
    action_description: str
    details_html: str = ""
    approved: Optional[bool] = None
    event: threading.Event = field(default_factory=threading.Event)

    def to_html(self) -> str:
        image_html = ""
        if os.path.exists(APPROVAL_MASCOT_PATH):
            image_url = APPROVAL_MASCOT_PATH.replace("\\", "/")
            if not image_url.startswith("/"):
                image_url = f"/{image_url}"
            image_html = f"""
            <td style="width: 280px; vertical-align: top; text-align: center; padding-left: 18px;">
                <img src="file://{image_url}" width="256" height="256" style="width: 256px; height: 256px;" />
            </td>
            """

        return f"""
        <div style="font-family:'Segoe UI',sans-serif;">
            <table style="border-collapse: collapse; width: 100%;">
                <tr>
                    <td style="vertical-align: top;">
                        <p>{self.intro}</p>
                        <p><b>{self.action_description}</b></p>
                        {self.details_html}
                    </td>
                    {image_html}
                </tr>
            </table>
        </div>
        """


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
