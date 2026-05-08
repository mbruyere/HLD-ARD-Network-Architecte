"""
Canned VyOS CLI outputs for Agent 6 (Monitoring) tests.

These simulate the output of VyOS ``show`` commands collected by Agent 6
via SSH/CLI polling from the NetLab virtual lab infrastructure.
"""

# ---------------------------------------------------------------------------
# show interfaces  (T7.1.1)
# ---------------------------------------------------------------------------

SHOW_INTERFACES = """\
Codes: S - State, L - Link, u - Up, D - Down, A - Admin Down
Interface    IP Address         S/L  Description
---------    ----------         ---  -----------
eth0         10.1.100.1/24      u/u  Employee-VLAN100
eth0.110     10.1.110.1/24      u/u  Voice-VLAN110
eth1         10.1.255.1/30      u/u  Transit-VLAN300
eth2         203.0.113.1/30     u/u  Internet-uplink
lo           127.0.0.1/8        u/u
"""

SHOW_INTERFACES_DOWN = """\
Codes: S - State, L - Link, u - Up, D - Down, A - Admin Down
Interface    IP Address         S/L  Description
---------    ----------         ---  -----------
eth0         10.1.100.1/24      u/u  Employee-VLAN100
eth0.110     10.1.110.1/24      u/u  Voice-VLAN110
eth0.140     10.1.140.1/24      D/D  Guest-VLAN140
eth1         10.1.255.1/30      u/u  Transit-VLAN300
eth2         203.0.113.1/30     u/u  Internet-uplink
lo           127.0.0.1/8        u/u
"""

# ---------------------------------------------------------------------------
# show firewall  (T7.1.2)
# ---------------------------------------------------------------------------

SHOW_FIREWALL = """\
Rule  Action  Source             Dest               Proto  Hits
----  ------  ------             ----               -----  ----
10    accept  10.1.140.0/24      0.0.0.0/0          any    15432
20    drop    10.1.140.0/24      10.1.100.0/16      any    342
"""

SHOW_FIREWALL_EMPTY = """\
Rule  Action  Source             Dest               Proto  Hits
----  ------  ------             ----               -----  ----
"""

SHOW_FIREWALL_MISSING_RULE = """\
Rule  Action  Source             Dest               Proto  Hits
----  ------  ------             ----               -----  ----
10    accept  10.1.140.0/24      0.0.0.0/0          any    15432
"""

# ---------------------------------------------------------------------------
# show vrrp  (T7.1.3)
# ---------------------------------------------------------------------------

SHOW_VRRP_MASTER = """\
Name         Interface  VRID  State   Priority  VIP
-----------  ---------  ----  ------  --------  ----
USF-HA       eth0       10    MASTER  200       10.1.100.254
"""

SHOW_VRRP_BACKUP = """\
Name         Interface  VRID  State   Priority  VIP
-----------  ---------  ----  ------  --------  ----
USF-HA       eth0       10    BACKUP  100       10.1.100.254
"""

# ---------------------------------------------------------------------------
# show ip route  (T7.1.4)
# ---------------------------------------------------------------------------

SHOW_IP_ROUTE = """\
Codes: K - kernel, C - connected, S - static, O - OSPF, B - BGP
S>*  0.0.0.0/0 [1/0] via 203.0.113.2, eth2
C>*  10.1.100.0/24 is directly connected, eth0
C>*  10.1.255.0/30 is directly connected, eth1
O>*  10.1.200.0/24 [110/20] via 10.1.255.2, eth1
"""

# ---------------------------------------------------------------------------
# show configuration commands  (T7.1.5 / T8.1 compliance comparison)
# ---------------------------------------------------------------------------

SHOW_CONFIG_COMPLIANT = """\
set firewall name GUEST-TO-INTERNET default-action accept
set firewall name GUEST-TO-INTERNET rule 10 action accept
set firewall name GUEST-TO-INTERNET rule 10 source address 10.1.140.0/24
set firewall name GUEST-TO-USER default-action drop
set firewall name GUEST-TO-USER rule 10 action drop
set firewall name GUEST-TO-USER rule 10 source address 10.1.140.0/24
set firewall name GUEST-TO-USER rule 10 destination address 10.1.100.0/16
"""

SHOW_CONFIG_MISSING_RULE = """\
set firewall name GUEST-TO-INTERNET default-action accept
set firewall name GUEST-TO-INTERNET rule 10 action accept
set firewall name GUEST-TO-INTERNET rule 10 source address 10.1.140.0/24
"""

SHOW_CONFIG_EXTRA_RULE = """\
set firewall name GUEST-TO-INTERNET default-action accept
set firewall name GUEST-TO-INTERNET rule 10 action accept
set firewall name GUEST-TO-INTERNET rule 10 source address 10.1.140.0/24
set firewall name GUEST-TO-USER default-action drop
set firewall name GUEST-TO-USER rule 10 action drop
set firewall name GUEST-TO-USER rule 10 source address 10.1.140.0/24
set firewall name GUEST-TO-USER rule 10 destination address 10.1.100.0/16
set firewall name ROGUE-RULE default-action accept
"""

# ---------------------------------------------------------------------------
# show system resources  (for alert thresholds T7.2.4)
# ---------------------------------------------------------------------------

SHOW_SYSTEM_RESOURCES_NORMAL = """\
CPU:  12%
Memory: 45% (256MB / 512MB)
Uptime: 14 days 3:22:15
"""

SHOW_SYSTEM_RESOURCES_HIGH_CPU = """\
CPU:  92%
Memory: 78% (400MB / 512MB)
Uptime: 14 days 3:22:15
"""
