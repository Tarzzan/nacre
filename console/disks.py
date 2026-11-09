"""Inventaire Linux indépendant du modèle de NAS. Aucune commande destructive."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def json_command(args, timeout=15):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return json.loads(result.stdout), result.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None


def normalize_inventory(payload):
    disks, volumes = [], []
    def visit(node, disk=None):
        kind = node.get('type', '')
        if kind == 'loop':
            return
        path = node.get('path') or '/dev/' + node['name']
        mounts = node.get('mountpoints') or ([node['mountpoint']] if node.get('mountpoint') else [])
        mounts = [x for x in mounts if x]
        if kind == 'disk':
            disk = {'id': hashlib.sha256(path.encode()).hexdigest()[:16], 'path': path,
                    'name': node['name'], 'model': (node.get('model') or '').strip(),
                    'bytes': int(node.get('size') or 0), 'transport': node.get('tran') or ('nvme' if node['name'].startswith('nvme') else 'inconnu'),
                    'rotational': bool(node.get('rota')), 'removable': bool(node.get('rm')), 'readonly': bool(node.get('ro')),
                    'system': False, 'volumes': []}
            disks.append(disk)
        if mounts or node.get('fstype'):
            filesystem = node.get('fstype') or 'inconnu'
            volume = {'path': path, 'name': node['name'], 'type': kind, 'filesystem': filesystem,
                      'label': node.get('label') or '', 'mountpoints': mounts, 'bytes': int(node.get('size') or 0),
                      'readonly': bool(node.get('ro')), 'disk_id': disk['id'] if disk else None,
                      'native_snapshot_family': 'btrfs' if filesystem == 'btrfs' else 'zfs' if filesystem == 'zfs' else 'lvm' if kind == 'lvm' else None}
            volumes.append(volume)
            if disk:
                disk['volumes'].append(volume['name'])
                disk['system'] |= '/' in mounts or '/boot' in mounts or '/boot/efi' in mounts
        for child in node.get('children', []):
            visit(child, disk)
    for node in payload.get('blockdevices', []):
        visit(node)
    return disks, volumes


def inventory(root):
    payload, code = json_command(['lsblk', '-J', '-b', '-o', 'NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS,MODEL,TRAN,RO,RM,ROTA'])
    if payload is None:
        payload, code = json_command(['lsblk', '-J', '-b', '-o', 'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,MODEL'])
    disks, volumes = normalize_inventory(payload or {})
    all_mounts, _ = json_command(['findmnt', '-J', '-l', '-o', 'TARGET,SOURCE,FSTYPE'])
    known = {m for volume in volumes for m in volume['mountpoints']}
    for mount in (all_mounts or {}).get('filesystems', []):
        filesystem, target = mount.get('fstype', ''), mount.get('target', '')
        if filesystem not in ('zfs', 'btrfs', 'ext4', 'xfs', 'ntfs', 'exfat', 'vfat', 'cifs', 'nfs', 'nfs4', 'fuseblk') or target in known:
            continue
        try:
            space = shutil.disk_usage(target)
        except OSError:
            continue
        volumes.append({'path': mount.get('source'), 'name': mount.get('source'), 'type': 'mounted-filesystem',
                        'filesystem': filesystem, 'label': '', 'mountpoints': [target], 'bytes': space.total,
                        'readonly': not os.access(target, os.W_OK), 'disk_id': None,
                        'native_snapshot_family': 'zfs' if filesystem == 'zfs' else 'btrfs' if filesystem == 'btrfs' else None})
    mounted, _ = json_command(['findmnt', '-J', '-T', str(root), '-o', 'TARGET,SOURCE,FSTYPE'])
    current = (mounted or {}).get('filesystems', [{}])[0]
    capacity = shutil.disk_usage(root)
    return {'platform': platform.system(), 'architecture': platform.machine(), 'disks': disks, 'volumes': volumes,
            'current': {**current, 'total': capacity.total, 'used': capacity.used, 'free': capacity.free},
            'tools': {name: bool(shutil.which(name)) for name in ('smartctl', 'btrfs', 'zfs', 'lvs')},
            'supported': payload is not None,
            'operations': {'inventory': True, 'smart_read': bool(shutil.which('smartctl')), 'format': False, 'system_unmount': False},
            'note': 'Les opérations exposées consultent le matériel et sa santé ; elles ne modifient pas les partitions.'}


def normalize_smart(payload, code):
    payload = payload or {}
    status = payload.get('smartctl', {}).get('exit_status', code)
    messages = payload.get('smartctl', {}).get('messages', [])
    permission = any('permission' in str(x.get('string', '')).lower() or 'operation not permitted' in str(x.get('string', '')).lower() for x in messages)
    if permission:
        return {'state': 'permission_required', 'message': 'Le service nécessite un accès système en lecture au périphérique pour consulter SMART.'}
    if not payload or status is None or status & 0b111:
        return {'state': 'unavailable', 'message': 'SMART indisponible avec cet accès ou ce contrôleur. Aucun état de santé n’est supposé.'}
    nvme = payload.get('nvme_smart_health_information_log', {})
    passed = payload.get('smart_status', {}).get('passed')
    return {'state': 'warning' if passed is False or status & 0b11111000 else 'ok' if passed is True else 'unknown',
            'passed': passed, 'temperature': payload.get('temperature', {}).get('current'),
            'power_on_hours': payload.get('power_on_time', {}).get('hours', nvme.get('power_on_hours')),
            'percentage_used': nvme.get('percentage_used'), 'available_spare': nvme.get('available_spare'),
            'media_errors': nvme.get('media_errors'), 'critical_warning': nvme.get('critical_warning'),
            'exit_status': status}


def health(root, identifier):
    device = next((d for d in inventory(root)['disks'] if d['id'] == identifier), None)
    if not device:
        raise ValueError('Périphérique inconnu.')
    binary = shutil.which('smartctl')
    if not binary:
        return {'state': 'tool_missing', 'message': 'smartmontools doit être installé sur le matériel cible.'}
    payload, code = json_command([binary, '-j', '-i', '-H', '-A', '-n', 'standby', device['path']], timeout=20)
    return {'device': device['name'], **normalize_smart(payload, code)}
