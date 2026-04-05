// ============================================================================
// Neo4j SSoT → Firewall Configuration State Extraction Queries
// ============================================================================
// These Cypher queries extract the full firewall configuration state from the
// Neo4j SSoT for rendering by the Jinja2 pipeline.
//
// The Orchestration Agent (Agent 5) executes these queries before each
// rendering cycle. The result set feeds directly into the Jinja2 template
// context as structured JSON.
// ============================================================================

// ---------------------------------------------------------------------------
// QUERY 1: Firewall Device Inventory
// Returns: All firewall devices with their pair membership and HA role
// Template variable: {{ firewalls }}
// ---------------------------------------------------------------------------
MATCH (d:Device)-[:MEMBER_OF_PAIR]->(fp:FirewallPair)
WHERE d.deviceRole IN ['USER_FW', 'DMZ_FW']
  AND d.lifecycleState = 'ACTIVE'
OPTIONAL MATCH (d)-[:LOCATED_AT]->(s:Site)
RETURN d.deviceId       AS device_id,
       d.hostname       AS hostname,
       d.vendor         AS vendor,
       d.model          AS model,
       d.deviceRole     AS device_role,
       d.haRole         AS ha_role,
       d.os             AS os,
       d.osVersion      AS os_version,
       fp.pairId        AS pair_id,
       fp.name          AS pair_name,
       fp.function      AS pair_function,
       fp.haModel       AS ha_model,
       fp.failoverTime  AS failover_time,
       fp.virtualIp     AS virtual_ip,
       s.siteId         AS site_id,
       s.name           AS site_name
ORDER BY d.deviceRole, d.deviceId;

// ---------------------------------------------------------------------------
// QUERY 2: Zone Definitions
// Returns: All security zones with their properties
// Template variable: {{ zones }}
// ---------------------------------------------------------------------------
MATCH (z:Zone)
WHERE z.lifecycleState IS NULL OR z.lifecycleState <> 'DECOMMISSIONED'
RETURN z.zoneId         AS zone_id,
       z.name           AS zone_name,
       z.type           AS zone_type,
       z.securityLevel  AS security_level,
       z.defaultPolicy  AS default_policy
ORDER BY z.securityLevel DESC;

// ---------------------------------------------------------------------------
// QUERY 3: Segments and their Zone Membership
// Returns: Population segments with VLAN, subnet, and zone assignments
// Template variable: {{ segments }}
// ---------------------------------------------------------------------------
MATCH (seg:Segment)-[:BELONGS_TO_ZONE]->(z:Zone)
OPTIONAL MATCH (v:VLAN)-[:CARRIES]->(seg)
OPTIONAL MATCH (sub:Subnet)-[:SERVES]->(seg)
WHERE seg.lifecycleState IS NULL OR seg.lifecycleState <> 'DECOMMISSIONED'
RETURN seg.segmentId      AS segment_id,
       seg.name           AS segment_name,
       seg.population     AS population,
       seg.qosDscp        AS qos_dscp,
       seg.internetAccess AS internet_access,
       seg.internalAccess AS internal_access,
       v.vlanId           AS vlan_id,
       v.name             AS vlan_name,
       sub.prefix         AS subnet_prefix,
       sub.gatewayIp      AS gateway_ip,
       z.zoneId           AS zone_id,
       z.name             AS zone_name,
       z.type             AS zone_type
ORDER BY v.vlanId;

// ---------------------------------------------------------------------------
// QUERY 4: Active Firewall Policies with Rules
// Returns: All active policies and their child firewall rules, linked to
//          source/destination zones and target devices
// Template variable: {{ policies }}
// ---------------------------------------------------------------------------
MATCH (pol:Policy)-[:APPLIED_TO]->(d:Device)
WHERE pol.type = 'FIREWALL_ZONE_POLICY'
  AND pol.lifecycleState = 'ACTIVE'
  AND d.deviceRole IN ['USER_FW', 'DMZ_FW']
WITH pol, d
MATCH (pol)-[:GOVERNS]->(seg:Segment)-[:BELONGS_TO_ZONE]->(src_zone:Zone)
OPTIONAL MATCH (fr:FirewallRule)-[:ENFORCES]->(pol)
OPTIONAL MATCH (fr)-[:FROM_ZONE]->(fz:Zone)
OPTIONAL MATCH (fr)-[:TO_ZONE]->(tz:Zone)
RETURN pol.policyId           AS policy_id,
       pol.name               AS policy_name,
       pol.type               AS policy_type,
       d.deviceId             AS target_device_id,
       d.hostname             AS target_hostname,
       d.deviceRole           AS target_device_role,
       fr.ruleId              AS rule_id,
       fr.ruleNumber          AS rule_number,
       fr.action              AS action,
       fr.protocol            AS protocol,
       fr.sourcePort          AS source_port,
       fr.destPort            AS dest_port,
       fr.logging             AS logging,
       fr.businessJustification AS justification,
       COALESCE(fz.name, src_zone.name) AS source_zone,
       COALESCE(fz.type, src_zone.type) AS source_zone_type,
       tz.name                AS dest_zone,
       tz.type                AS dest_zone_type
ORDER BY d.deviceId, fr.ruleNumber;

// ---------------------------------------------------------------------------
// QUERY 5: Intent-to-Policy Traceability
// Returns: Active intents with their translated policies — for audit headers
// Template variable: {{ intents }}
// ---------------------------------------------------------------------------
MATCH (i:Intent)-[:TRANSLATED_TO]->(it:IntentTranslation)-[:GENERATES_POLICY]->(pol:Policy)
WHERE i.status = 'ACTIVE'
  AND pol.type = 'FIREWALL_ZONE_POLICY'
RETURN i.intentId         AS intent_id,
       i.statement        AS intent_statement,
       i.type             AS intent_type,
       i.priority         AS priority,
       pol.policyId       AS policy_id,
       pol.name           AS policy_name,
       it.translationId   AS translation_id,
       it.translatedAt    AS translated_at
ORDER BY i.priority;

// ---------------------------------------------------------------------------
// QUERY 6: VLANs Assigned to Firewall Interfaces
// Returns: VLAN-to-interface mapping for each firewall device
// Template variable: {{ fw_interfaces }}
// ---------------------------------------------------------------------------
MATCH (d:Device)-[:HAS_INTERFACE]->(iface:Interface)
WHERE d.deviceRole IN ['USER_FW', 'DMZ_FW']
  AND d.lifecycleState = 'ACTIVE'
OPTIONAL MATCH (iface)-[:CARRIES_VLAN]->(v:VLAN)
OPTIONAL MATCH (v)-[:PART_OF_SUBNET]->(sub:Subnet)
OPTIONAL MATCH (iface)-[:CONNECTS_TO]->(remote_iface:Interface)<-[:HAS_INTERFACE]-(remote_dev:Device)
RETURN d.deviceId          AS device_id,
       d.hostname          AS hostname,
       d.deviceRole        AS device_role,
       iface.interfaceId   AS interface_id,
       iface.name          AS interface_name,
       iface.interfaceType AS interface_type,
       iface.description   AS description,
       iface.adminState    AS admin_state,
       v.vlanId            AS vlan_id,
       v.name              AS vlan_name,
       sub.prefix          AS subnet_prefix,
       sub.gatewayIp       AS gateway_ip,
       remote_dev.hostname AS connected_to_device,
       remote_iface.name   AS connected_to_interface
ORDER BY d.deviceId, v.vlanId;

// ---------------------------------------------------------------------------
// QUERY 7: NAT Rules (User Services Firewall)
// Returns: NAT/PAT rules for user internet access
// Template variable: {{ nat_rules }}
// ---------------------------------------------------------------------------
MATCH (pol:Policy)-[:APPLIED_TO]->(d:Device)
WHERE pol.type = 'NAT_RULE'
  AND pol.lifecycleState = 'ACTIVE'
  AND d.deviceRole = 'USER_FW'
OPTIONAL MATCH (fr:FirewallRule)-[:ENFORCES]->(pol)
OPTIONAL MATCH (fr)-[:FROM_ZONE]->(src:Zone)
OPTIONAL MATCH (fr)-[:TO_ZONE]->(dst:Zone)
OPTIONAL MATCH (seg:Segment)<-[:GOVERNS]-(pol)
OPTIONAL MATCH (sub:Subnet)-[:SERVES]->(seg)
RETURN pol.policyId     AS policy_id,
       pol.name         AS policy_name,
       d.deviceId       AS device_id,
       d.hostname       AS hostname,
       fr.ruleId        AS rule_id,
       fr.ruleNumber    AS rule_number,
       fr.action        AS nat_type,
       src.name         AS source_zone,
       dst.name         AS dest_zone,
       sub.prefix       AS source_network,
       fr.destPort      AS translated_address,
       fr.businessJustification AS justification
ORDER BY fr.ruleNumber;

// ---------------------------------------------------------------------------
// QUERY 8: Inter-Firewall Transit Link
// Returns: The transit VLAN/subnet between USF and DMZFW pairs
// Template variable: {{ fw_transit }}
// ---------------------------------------------------------------------------
MATCH (v:VLAN)
WHERE v.vlanId = 300
OPTIONAL MATCH (sub:Subnet)-[:PART_OF_VLAN]->(v)
RETURN v.vlanId     AS vlan_id,
       v.name       AS vlan_name,
       sub.prefix   AS transit_prefix,
       sub.gatewayIp AS transit_gateway;
