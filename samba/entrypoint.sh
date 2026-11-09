#!/bin/sh
set -eu
password=$(cat /run/secrets/smb_password)
test -n "$password"
printf '%s\n%s\n' "$password" "$password" | smbpasswd -s -a nas
unset password
if test -f /etc/nas-autonome/users.tsv; then
    while IFS="$(printf '\t')" read -r name uid; do
        test -n "$name" || continue
        if ! id -u "$name" >/dev/null 2>&1; then
            adduser -D -H -u "$uid" -G nas "$name"
        fi
    done < /etc/nas-autonome/users.tsv
fi
mkdir -p /run/samba
config=/etc/samba/smb.conf
test ! -f /etc/nas-autonome/smb.conf || config=/etc/nas-autonome/smb.conf
testparm -s "$config" >/dev/null
exec smbd --foreground --no-process-group --debug-stdout --configfile="$config"
