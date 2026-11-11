"""Run inside the derived image, with --network none and no NAS data mounts.

Uses real Frigate publish/filter/IPC code and ws4py; only browser clients are
synthetic. The unpatched method is reconstructed in memory as a negative control.
"""
import ast
import hashlib
import json
import socket
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import zmq
sys.path.insert(0, '/opt/frigate')
import frigate.comms.ws as upstream
from frigate.comms.inter_process import InterProcessCommunicator
from ws4py.websocket import WebSocket
from patch_websocket import BEFORE, AFTER, UPSTREAM_SHA256

source = Path(upstream.__file__).read_text()
assert source.count(AFTER) == 1, 'Derived image patch missing'
original = source.replace(AFTER, BEFORE)
assert hashlib.sha256(original.encode()).hexdigest() == UPSTREAM_SHA256
node = next(n for n in ast.parse(original).body if isinstance(n, ast.ClassDef) and n.name == 'WebSocketClient')
method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == 'publish')
scope = dict(vars(upstream))
exec(compile(ast.Module(body=[method], type_ignores=[]), '<upstream-publish>', 'exec'), scope)
original_publish = scope['publish']


class Receiver:
    terminated = False
    environ = {}
    def __init__(self, error=None):
        self.messages = []
        self.error = error
    def send(self, message):
        if self.error:
            raise self.error
        self.messages.append(json.loads(message))


class ClosingReceiver(Receiver):
    def __init__(self):
        super().__init__()
        self.left, self.right = socket.socketpair()
        self.ws = WebSocket(self.left)
    def send(self, message):
        # Real ws4py exception, after Frigate's terminated check has passed.
        self.ws.client_terminated = self.ws.server_terminated = True
        self.ws.send(message)
    def close(self):
        self.left.close(); self.right.close()


def client(*receivers):
    result = object.__new__(upstream.WebSocketClient)
    result.config = SimpleNamespace(cameras={})
    result.websocket_server = SimpleNamespace(manager=SimpleNamespace(
        lock=threading.Lock(), websockets=dict(enumerate(receivers))))
    return result


class WebSocketRegression(unittest.TestCase):
    def test_original_failure_and_patched_delivery(self):
        closed, healthy = ClosingReceiver(), Receiver()
        self.addCleanup(closed.close)
        subject = client(closed, healthy)
        with self.assertRaisesRegex(RuntimeError, '^Cannot send on a terminated websocket$'):
            original_publish(subject, 'model_state', '{}')
        self.assertEqual(healthy.messages, [])
        subject.publish('model_state', '{}')
        self.assertEqual(len(healthy.messages), 1)

    def test_other_errors_remain_visible(self):
        subject = client(Receiver(RuntimeError('unrelated failure')))
        with self.assertRaisesRegex(RuntimeError, 'unrelated failure'):
            subject.publish('model_state', '{}')

    def test_existing_disconnects_and_already_terminated(self):
        healthy = Receiver()
        skipped = Receiver(AssertionError('must not send'))
        skipped.terminated = True
        subject = client(skipped, Receiver(ConnectionResetError()), Receiver(BrokenPipeError()), Receiver(ValueError()), healthy)
        subject.publish('model_state', '{}')
        self.assertEqual(len(healthy.messages), 1)

    def test_unknown_and_restricted_messages_stay_filtered(self):
        receiver = Receiver()
        subject = client(receiver)
        subject.publish('unknown-topic', '{}')
        subject.config.cameras = {'private': SimpleNamespace(zones={})}
        subject.publish('private/motion', 'ON')  # no authorized role header
        self.assertEqual(receiver.messages, [])

    def test_ipc_thread_survives_repeated_disconnects(self):
        closed, healthy = ClosingReceiver(), Receiver()
        self.addCleanup(closed.close)
        subject = client(closed, healthy)
        Path('/tmp/cache').mkdir(parents=True, exist_ok=True)
        ipc = InterProcessCommunicator()
        context = zmq.Context()
        request = context.socket(zmq.REQ)
        request.setsockopt(zmq.RCVTIMEO, 3000)
        request.setsockopt(zmq.SNDTIMEO, 3000)
        request.connect('ipc:///tmp/cache/comms')
        errors = []
        with patch('threading.excepthook', side_effect=lambda args: errors.append(args.exc_type.__name__)):
            ipc.subscribe(lambda topic, value: subject.publish(topic, value))
            try:
                for number in range(100):
                    request.send_json(['model_state', str(number)])
                    self.assertEqual(request.recv_json(), [])
                self.assertTrue(ipc.reader_thread.is_alive())
                self.assertEqual(len(healthy.messages), 100)
                self.assertEqual(errors, [])
            finally:
                request.close(linger=0); context.destroy(linger=0); ipc.stop()


if __name__ == '__main__':
    unittest.main(verbosity=2)
