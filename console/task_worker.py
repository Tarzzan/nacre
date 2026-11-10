#!/usr/bin/env python3
"""Processus de tâche indépendant du serveur web ; progression persistante dans SQLite."""
import os
import sys
import server

if __name__ == '__main__':
    os.umask(0o077)
    from installation_lock import acquire
    process_installation_lock = acquire(server.ROOT)
    server.initialize()
    server.protection().run_job(sys.argv[1])
