#!/usr/bin/env python3
"""Tiny SSH/SCP helper for the NeuroDrive Pi 5 (Node 2).

Creds come from env so nothing secret is committed:
    PI_HOST (default 192.168.1.16)  PI_USER (default admin)  PI_PASS

Usage:
    python pi_ssh.py run "uname -a"
    python pi_ssh.py put localfile /remote/path
    python pi_ssh.py get /remote/path localfile
"""
import os
import sys
import paramiko

HOST = os.environ.get("PI_HOST", "192.168.1.16")
USER = os.environ.get("PI_USER", "admin")
PASS = os.environ.get("PI_PASS")  # required; never hard-code (export PI_PASS=...)
if not PASS:
    sys.exit("PI_PASS env var is required (export PI_PASS=... before running)")


def client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=15)
    return c


def main():
    op = sys.argv[1]
    c = client()
    if op == "run":
        cmd = sys.argv[2]
        stdin, stdout, stderr = c.exec_command(cmd, timeout=120)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
        sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        c.close()
        sys.exit(rc)
    elif op in ("put", "get"):
        sftp = c.open_sftp()
        a, b = sys.argv[2], sys.argv[3]
        (sftp.put if op == "put" else sftp.get)(a, b)
        sftp.close()
        c.close()
        print(f"{op} OK: {a} -> {b}")
    else:
        sys.exit(f"unknown op {op}")


if __name__ == "__main__":
    main()
