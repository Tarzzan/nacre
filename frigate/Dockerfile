ARG FRIGATE_IMAGE
FROM ${FRIGATE_IMAGE}
COPY patch_websocket.py /opt/nacre/patch_websocket.py
RUN python3 /opt/nacre/patch_websocket.py
LABEL org.nacre.frigate.patch="terminated-websocket-v1"
