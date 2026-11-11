"""Narrow compatibility patch for the pinned Frigate 0.18.2 images.

Never silently patch a different upstream implementation. See
docs/FRIGATE-WEBSOCKET.md for the incident, reproduction and removal criteria.
"""
import hashlib
from pathlib import Path

UPSTREAM_SHA256 = '06deb021cd5f193c0177dad9837ea5f77b96256c05996d77aff563d5587f6cd2'
BEFORE = '''            except (ConnectionResetError, BrokenPipeError, ValueError):
                pass
'''
AFTER = BEFORE + '''            except RuntimeError as error:
                # The connection can close between the terminated check and send.
                if str(error) != "Cannot send on a terminated websocket":
                    raise
'''


def patched(source):
    if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA256:
        raise RuntimeError('Unsupported Frigate ws.py; review the patch before upgrading.')
    text = source.decode('utf-8')
    if text.count(BEFORE) != 1:
        raise RuntimeError('Expected WebSocket handler was not found exactly once.')
    result = text.replace(BEFORE, AFTER).encode('utf-8')
    compile(result, 'frigate/comms/ws.py', 'exec')
    return result


if __name__ == '__main__':
    target = Path('/opt/frigate/frigate/comms/ws.py')
    target.write_bytes(patched(target.read_bytes()))
    print('Nacre: terminated-websocket-v1 applied to the verified Frigate source.')
