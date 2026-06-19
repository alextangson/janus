# Janus HAOS add-on。上下文 = repo root(需 pyproject + gatekeeper/ + service/ + 烤入的 app dist)。
ARG BUILD_FROM
FROM ${BUILD_FROM}

# Janus 服务依赖 + 包。HA base-python 已含 python3/pip/s6/bashio。
WORKDIR /opt/janus
COPY pyproject.toml ./
COPY gatekeeper/ ./gatekeeper/
COPY service/ ./service/
RUN pip install --no-cache-dir ".[service]"

# 烤入 janus-app 的 ingress dist(由 build-addon-app.sh 预先构建并拷进 app/)。
COPY deploy/addon/janus/app/ /opt/janus-app/

# s6-overlay v3 服务(rootfs 覆盖到 /)。run 脚本必须可执行,否则 s6 不拉起服务。
COPY deploy/addon/janus/rootfs/ /
RUN chmod +x /etc/s6-overlay/s6-rc.d/janus/run

ENV PYTHONUNBUFFERED=1
WORKDIR /opt/janus
