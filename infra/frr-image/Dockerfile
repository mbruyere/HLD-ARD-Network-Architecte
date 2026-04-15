# IBN closed-loop — native-multi-arch FRR container (Slice 5)
#
# Docker Hub's frrouting/frr image is amd64-only; on ARM64 hosts it
# requires QEMU user-mode emulation and the daemons crash on boot.
# This image is built from debian:stable-slim (multi-arch) + FRR
# from Debian's apt repo, which gives us native ARM64 + x86_64
# support in ~100 MB.
#
# Published locally as `ibn-frr:local`. The IBN Provisioner maps
# (vendor=FRR, platform=frr) → this image via the clab_yaml
# _KIND_MAP dispatch.
#
# Build:  docker build -t ibn-frr:local infra/frr-image/
# Probe:  docker run --rm --privileged ibn-frr:local &
#         docker exec <container> vtysh -c "show version"

FROM debian:stable-slim

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        frr frr-pythontools \
        iproute2 iputils-ping \
        tini; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Enable the core FRR daemons. Operators edit /etc/frr/daemons to
# toggle individual protocols; the Slice 5 templates currently
# configure zebra (always on) + bgpd + ospfd as a baseline.
RUN set -eux; \
    for d in bgpd ospfd ospf6d isisd; do \
        sed -i "s/^${d}=no/${d}=yes/" /etc/frr/daemons; \
    done

# Seed a minimal running config so the daemons start cleanly.
# The closed-loop pipeline will overwrite this with HLD-driven
# config on first push.
RUN cat > /etc/frr/frr.conf <<'EOF'
frr version 9.1
frr defaults traditional
hostname frr-default
log syslog informational
no ipv6 forwarding
!
line vty
!
end
EOF

RUN chown frr:frr /etc/frr/frr.conf /etc/frr/daemons \
 && chmod 640 /etc/frr/frr.conf /etc/frr/daemons

# tini reaps zombies from FRR's fork/exec model cleanly
ENTRYPOINT ["/usr/bin/tini", "--"]

# /usr/lib/frr/frrinit.sh starts all enabled daemons in order
CMD ["/bin/sh", "-c", "/usr/lib/frr/frrinit.sh start && tail -F /var/log/frr/*.log"]
