"""Short-lived dashboard approvals; no action runs without an explicit answer."""

from copy import deepcopy
import threading
import time
import uuid


class ApprovalQueue:
    def __init__(self, timeout=90):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending = {}

    def confirm(self, name, details):
        key = uuid.uuid4().hex
        item = {'id': key, 'tool': name, 'details': deepcopy(details),
                'expires': time.monotonic() + self.timeout, 'event': threading.Event(), 'approved': False}
        with self._lock:
            self._pending[key] = item
        try:
            answered = item['event'].wait(self.timeout)
            return answered and item['approved'] and time.monotonic() < item['expires']
        finally:
            with self._lock:
                self._pending.pop(key, None)

    def pending(self):
        with self._lock:
            return [{key: deepcopy(item[key]) for key in ('id','tool','details')}
                    for item in self._pending.values() if time.monotonic() < item['expires'] and not item['event'].is_set()]

    def answer(self, key, approved):
        if type(approved) is not bool:
            raise ValueError('approved must be a boolean')
        with self._lock:
            item = self._pending.get(key)
            if item is None or item['event'].is_set() or time.monotonic() >= item['expires']:
                raise ValueError('Approval is missing, expired, or already answered')
            item['approved'] = approved
            item['event'].set()

    def close(self):
        with self._lock:
            for item in self._pending.values():
                item['approved'] = False
                item['event'].set()
