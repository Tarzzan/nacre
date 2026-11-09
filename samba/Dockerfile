FROM alpine:3.23@sha256:469c9ea410b9215eaee7976ba6c0639039b444be8e5d638f7abbada189971eb2
ARG NAS_UID=1000
ARG NAS_GID=1000
RUN apk add --no-cache samba samba-client && \
    if getent group "$NAS_GID" >/dev/null; then printf 'nas:x:%s:\n' "$NAS_GID" >> /etc/group; else addgroup -g "$NAS_GID" nas; fi && \
    adduser -D -H -u "$NAS_UID" -G nas nas
COPY smb.conf /etc/samba/smb.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
EXPOSE 445
ENTRYPOINT ["/entrypoint.sh"]
