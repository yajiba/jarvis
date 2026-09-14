from concurrent.futures import ThreadPoolExecutor
import time
import unittest

from jarvis.api.approvals import ApprovalQueue


class ApprovalTests(unittest.TestCase):
    def test_explicit_answer_and_replay_rejection(self):
        queue=ApprovalQueue(timeout=2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(queue.confirm,'desktop_action',{'value':'20,30'})
            deadline=time.monotonic()+1
            while not queue.pending() and time.monotonic()<deadline:
                time.sleep(.001)
            key=queue.pending()[0]['id']
            with self.assertRaises(ValueError):
                queue.answer(key,'yes')
            queue.answer(key,True)
            self.assertTrue(result.result(timeout=1))
            with self.assertRaises(ValueError):
                queue.answer(key,True)
        self.assertEqual(queue.pending(),[])

    def test_timeout_and_shutdown_deny(self):
        self.assertFalse(ApprovalQueue(timeout=.001).confirm('tool',{}))
        queue=ApprovalQueue(timeout=2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(queue.confirm,'tool',{})
            deadline=time.monotonic()+1
            while not queue.pending() and time.monotonic()<deadline:
                time.sleep(.001)
            queue.close()
            self.assertFalse(result.result(timeout=1))
