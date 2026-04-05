// =============================================================================
// Neo4j Schema — Network Architecture Lifecycle Ontology
// Enterprise Campus Network / IBN Closed-Loop
// Version: 1.0 | March 2026
// Theoretical design — no live instance
// Compatible with: Neo4j 5.x (Community or Enterprise)
// =============================================================================


// =============================================================================
// SECTION 1 — CONSTRAINTS (Unique node identifiers)
// These enforce uniqueness and create backing indexes automatically.
// =============================================================================

// --- Layer 1: Infrastructure ---
CREATE CONSTRAINT site_id         IF NOT EXISTS FOR (n:Site)           REQUIRE n.siteId         IS UNIQUE;
CREATE CONSTRAINT device_id       IF NOT EXISTS FOR (n:Device)         REQUIRE n.deviceId       IS UNIQUE;
CREATE CONSTRAINT device_hostname IF NOT EXISTS FOR (n:Device)         REQUIRE n.hostname       IS UNIQUE;
CREATE CONSTRAINT iface_id        IF NOT EXISTS FOR (n:Interface)      REQUIRE n.interfaceId    IS UNIQUE;
CREATE CONSTRAINT plink_id        IF NOT EXISTS FOR (n:PhysicalLink)   REQUIRE n.linkId         IS UNIQUE;
CREATE CONSTRAINT llink_id        IF NOT EXISTS FOR (n:LogicalLink)    REQUIRE n.linkId         IS UNIQUE;
CREATE CONSTRAINT vlan_id         IF NOT EXISTS FOR (n:VLAN)           REQUIRE n.vlanId         IS UNIQUE;
CREATE CONSTRAINT vrf_id          IF NOT EXISTS FOR (n:VRF)            REQUIRE n.vrfId          IS UNIQUE;
CREATE CONSTRAINT subnet_id       IF NOT EXISTS FOR (n:Subnet)         REQUIRE n.subnetId       IS UNIQUE;
CREATE CONSTRAINT subnet_prefix   IF NOT EXISTS FOR (n:Subnet)         REQUIRE n.prefix         IS UNIQUE;
CREATE CONSTRAINT ip_address      IF NOT EXISTS FOR (n:IPAddress)      REQUIRE n.address        IS UNIQUE;
CREATE CONSTRAINT ippool_id       IF NOT EXISTS FOR (n:IPPool)         REQUIRE n.poolId         IS UNIQUE;
CREATE CONSTRAINT rtdomain_id     IF NOT EXISTS FOR (n:RoutingDomain)  REQUIRE n.domainId       IS UNIQUE;

// --- Layer 2: Topology & Segmentation ---
CREATE CONSTRAINT topology_id     IF NOT EXISTS FOR (n:Topology)       REQUIRE n.topologyId     IS UNIQUE;
CREATE CONSTRAINT tlayer_id       IF NOT EXISTS FOR (n:TopologyLayer)  REQUIRE n.layerId        IS UNIQUE;
CREATE CONSTRAINT zone_id         IF NOT EXISTS FOR (n:Zone)           REQUIRE n.zoneId         IS UNIQUE;
CREATE CONSTRAINT segment_id      IF NOT EXISTS FOR (n:Segment)        REQUIRE n.segmentId      IS UNIQUE;
CREATE CONSTRAINT fwpair_id       IF NOT EXISTS FOR (n:FirewallPair)   REQUIRE n.pairId         IS UNIQUE;
CREATE CONSTRAINT stackgrp_id     IF NOT EXISTS FOR (n:StackGroup)     REQUIRE n.groupId        IS UNIQUE;

// --- Layer 3: Architecture & Design ---
CREATE CONSTRAINT arch_id         IF NOT EXISTS FOR (n:Architecture)        REQUIRE n.archId        IS UNIQUE;
CREATE CONSTRAINT archver_id      IF NOT EXISTS FOR (n:ArchitectureVersion)  REQUIRE n.versionId     IS UNIQUE;
CREATE CONSTRAINT hld_id          IF NOT EXISTS FOR (n:HLDDocument)          REQUIRE n.docId         IS UNIQUE;
CREATE CONSTRAINT ard_id          IF NOT EXISTS FOR (n:ARDDocument)          REQUIRE n.docId         IS UNIQUE;
CREATE CONSTRAINT decision_id     IF NOT EXISTS FOR (n:DesignDecision)       REQUIRE n.decisionId    IS UNIQUE;
CREATE CONSTRAINT principle_id    IF NOT EXISTS FOR (n:DesignPrinciple)      REQUIRE n.principleId   IS UNIQUE;
CREATE CONSTRAINT buc_id          IF NOT EXISTS FOR (n:BusinessUseCase)      REQUIRE n.bucId         IS UNIQUE;
CREATE CONSTRAINT req_id          IF NOT EXISTS FOR (n:ComplianceRequirement) REQUIRE n.reqId        IS UNIQUE;
CREATE CONSTRAINT threat_id       IF NOT EXISTS FOR (n:ThreatVector)         REQUIRE n.threatId      IS UNIQUE;
CREATE CONSTRAINT capability_id   IF NOT EXISTS FOR (n:SecurityCapability)   REQUIRE n.capabilityId  IS UNIQUE;

// --- Layer 4: Policy & Intent ---
CREATE CONSTRAINT intent_id       IF NOT EXISTS FOR (n:Intent)              REQUIRE n.intentId      IS UNIQUE;
CREATE CONSTRAINT itrans_id       IF NOT EXISTS FOR (n:IntentTranslation)   REQUIRE n.translationId IS UNIQUE;
CREATE CONSTRAINT policy_id       IF NOT EXISTS FOR (n:Policy)              REQUIRE n.policyId      IS UNIQUE;
CREATE CONSTRAINT fwrule_id       IF NOT EXISTS FOR (n:FirewallRule)        REQUIRE n.ruleId        IS UNIQUE;
CREATE CONSTRAINT sgt_id          IF NOT EXISTS FOR (n:SecurityGroup)       REQUIRE n.groupId       IS UNIQUE;
CREATE CONSTRAINT sgt_tag         IF NOT EXISTS FOR (n:SecurityGroup)       REQUIRE n.tag           IS UNIQUE;

// --- Layer 5: Configuration & State ---
CREATE CONSTRAINT config_id       IF NOT EXISTS FOR (n:ConfigurationVersion) REQUIRE n.configId     IS UNIQUE;
CREATE CONSTRAINT opstate_id      IF NOT EXISTS FOR (n:OperationalState)     REQUIRE n.stateId      IS UNIQUE;
CREATE CONSTRAINT telemetry_id    IF NOT EXISTS FOR (n:TelemetryRecord)      REQUIRE n.recordId     IS UNIQUE;
CREATE CONSTRAINT assurance_id    IF NOT EXISTS FOR (n:AssuranceResult)      REQUIRE n.resultId     IS UNIQUE;
CREATE CONSTRAINT ssot_id         IF NOT EXISTS FOR (n:SSoT)                 REQUIRE n.ssotId       IS UNIQUE;

// --- Layer 6: Incidents ---
CREATE CONSTRAINT incident_id     IF NOT EXISTS FOR (n:Incident)            REQUIRE n.incidentId    IS UNIQUE;
CREATE CONSTRAINT alert_id        IF NOT EXISTS FOR (n:Alert)               REQUIRE n.alertId       IS UNIQUE;
CREATE CONSTRAINT rca_id          IF NOT EXISTS FOR (n:RootCause)           REQUIRE n.rcaId         IS UNIQUE;
CREATE CONSTRAINT remedy_id       IF NOT EXISTS FOR (n:Remediation)         REQUIRE n.remediationId IS UNIQUE;
CREATE CONSTRAINT probe_id        IF NOT EXISTS FOR (n:DiagnosticProbe)     REQUIRE n.probeId       IS UNIQUE;

// --- Layer 7: Change Management ---
CREATE CONSTRAINT cr_id           IF NOT EXISTS FOR (n:ChangeRequest)       REQUIRE n.crId          IS UNIQUE;
CREATE CONSTRAINT window_id       IF NOT EXISTS FOR (n:ChangeWindow)        REQUIRE n.windowId      IS UNIQUE;
CREATE CONSTRAINT approval_id     IF NOT EXISTS FOR (n:Approval)            REQUIRE n.approvalId    IS UNIQUE;
CREATE CONSTRAINT deploy_id       IF NOT EXISTS FOR (n:DeploymentEvent)     REQUIRE n.deployId      IS UNIQUE;
CREATE CONSTRAINT migration_id    IF NOT EXISTS FOR (n:MigrationPlan)       REQUIRE n.planId        IS UNIQUE;

// --- Layer 8: Lifecycle ---
CREATE CONSTRAINT lphase_id       IF NOT EXISTS FOR (n:LifecyclePhase)       REQUIRE n.phaseId       IS UNIQUE;
CREATE CONSTRAINT ltrans_id       IF NOT EXISTS FOR (n:LifecycleTransition)  REQUIRE n.transitionId  IS UNIQUE;
CREATE CONSTRAINT commission_id   IF NOT EXISTS FOR (n:CommissioningRecord)  REQUIRE n.recordId      IS UNIQUE;
CREATE CONSTRAINT decommission_id IF NOT EXISTS FOR (n:DecommissioningRecord) REQUIRE n.recordId     IS UNIQUE;

// --- Layer 9: People & Process ---
CREATE CONSTRAINT operator_id     IF NOT EXISTS FOR (n:Operator)     REQUIRE n.operatorId IS UNIQUE;
CREATE CONSTRAINT team_id         IF NOT EXISTS FOR (n:Team)         REQUIRE n.teamId     IS UNIQUE;
CREATE CONSTRAINT ticket_id       IF NOT EXISTS FOR (n:Ticket)       REQUIRE n.ticketId   IS UNIQUE;
CREATE CONSTRAINT sla_id          IF NOT EXISTS FOR (n:SLA)          REQUIRE n.slaId      IS UNIQUE;
CREATE CONSTRAINT sla_viol_id     IF NOT EXISTS FOR (n:SLAViolation) REQUIRE n.violationId IS UNIQUE;


// =============================================================================
// SECTION 2 — INDEXES (Frequent lookup properties not covered by constraints)
// =============================================================================

CREATE INDEX device_role          IF NOT EXISTS FOR (n:Device)              ON (n.deviceRole);
CREATE INDEX device_lifecycle     IF NOT EXISTS FOR (n:Device)              ON (n.lifecycleState);
CREATE INDEX device_site          IF NOT EXISTS FOR (n:Device)              ON (n.siteId);
CREATE INDEX iface_oper           IF NOT EXISTS FOR (n:Interface)           ON (n.operState);
CREATE INDEX iface_admin          IF NOT EXISTS FOR (n:Interface)           ON (n.adminState);
CREATE INDEX vlan_group           IF NOT EXISTS FOR (n:VLAN)                ON (n.vlanGroup);
CREATE INDEX vlan_lifecycle       IF NOT EXISTS FOR (n:VLAN)                ON (n.lifecycleState);
CREATE INDEX segment_population   IF NOT EXISTS FOR (n:Segment)             ON (n.population);
CREATE INDEX zone_type            IF NOT EXISTS FOR (n:Zone)                ON (n.type);
CREATE INDEX intent_status        IF NOT EXISTS FOR (n:Intent)              ON (n.status);
CREATE INDEX intent_type          IF NOT EXISTS FOR (n:Intent)              ON (n.type);
CREATE INDEX assurance_compliance IF NOT EXISTS FOR (n:AssuranceResult)     ON (n.compliance);
CREATE INDEX assurance_timestamp  IF NOT EXISTS FOR (n:AssuranceResult)     ON (n.timestamp);
CREATE INDEX telemetry_metric     IF NOT EXISTS FOR (n:TelemetryRecord)     ON (n.metric);
CREATE INDEX telemetry_timestamp  IF NOT EXISTS FOR (n:TelemetryRecord)     ON (n.timestamp);
CREATE INDEX incident_severity    IF NOT EXISTS FOR (n:Incident)            ON (n.severity);
CREATE INDEX incident_status      IF NOT EXISTS FOR (n:Incident)            ON (n.status);
CREATE INDEX cr_status            IF NOT EXISTS FOR (n:ChangeRequest)       ON (n.status);
CREATE INDEX cr_type              IF NOT EXISTS FOR (n:ChangeRequest)       ON (n.type);
CREATE INDEX archver_status       IF NOT EXISTS FOR (n:ArchitectureVersion) ON (n.status);
CREATE INDEX config_approved      IF NOT EXISTS FOR (n:ConfigurationVersion) ON (n.approved);
CREATE INDEX lifecycle_phase_name IF NOT EXISTS FOR (n:LifecyclePhase)      ON (n.name);
CREATE INDEX rca_category         IF NOT EXISTS FOR (n:RootCause)           ON (n.category);


// =============================================================================
// SECTION 3 — SEED DATA: Lifecycle Phases (static reference nodes)
// These are created once and referenced by all lifecycle transitions.
// =============================================================================

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-PLANNED'})
  SET lp.name = 'PLANNED', lp.description = 'Element defined in design; not yet approved for deployment';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-DESIGNED'})
  SET lp.name = 'DESIGNED', lp.description = 'Element specified in HLD/ARD; under review';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-APPROVED'})
  SET lp.name = 'APPROVED', lp.description = 'Change approved; ready for deployment';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-DEPLOYING'})
  SET lp.name = 'DEPLOYING', lp.description = 'Actively being provisioned';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-ACTIVE'})
  SET lp.name = 'ACTIVE', lp.description = 'In full production service';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-DEGRADED'})
  SET lp.name = 'DEGRADED', lp.description = 'Operational but with fault condition; service partially impaired';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-MAINTENANCE'})
  SET lp.name = 'MAINTENANCE', lp.description = 'In scheduled maintenance window';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-UPGRADING'})
  SET lp.name = 'UPGRADING', lp.description = 'Architecture upgrade in progress (MigrationPlan executing)';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-DECOMMISSIONING'})
  SET lp.name = 'DECOMMISSIONING', lp.description = 'Retirement in progress; dependencies being migrated';

MERGE (lp:LifecyclePhase {phaseId: 'PHASE-DECOMMISSIONED'})
  SET lp.name = 'DECOMMISSIONED', lp.description = 'Retired from service; preserved in graph for audit';


// =============================================================================
// SECTION 4 — EXAMPLE: Campus Architecture Bootstrap
// Demonstrates how to populate the ontology for the Enterprise Campus HLD v1.0
// =============================================================================

// --- Architecture root ---
MERGE (arch:Architecture {archId: 'ARCH-CAMPUS-01'})
  SET arch.name        = 'Enterprise Campus Network Architecture',
      arch.domain      = 'Campus Network',
      arch.owner       = 'Network Architecture Team',
      arch.createdAt   = datetime('2025-12-01T00:00:00Z');

// --- Architecture Version 1.0 ---
MERGE (v1:ArchitectureVersion {versionId: 'ARCHVER-1.0.0'})
  SET v1.version         = '1.0.0',
      v1.status          = 'ACTIVE',
      v1.approvedAt      = datetime('2025-12-15T00:00:00Z'),
      v1.changeRationale = 'Initial architecture definition',
      v1.breakingChange  = false;

MERGE (arch)-[:HAS_VERSION]->(v1);

// --- HLD Document ---
MERGE (hld:HLDDocument {docId: 'HLD-CAMPUS-001'})
  SET hld.title    = 'Enterprise Campus Network Architecture - High-Level Design',
      hld.version  = '1.0',
      hld.filePath = 'Enterprise_Campus_Network_HLD.md',
      hld.format   = 'MARKDOWN',
      hld.status   = 'APPROVED';

MERGE (v1)-[:BASED_ON_HLD]->(hld);

// --- ARD Documents ---
MERGE (ard_safe:ARDDocument {docId: 'ARD-SAFE-CAMPUS-001'})
  SET ard_safe.title     = 'Cisco SAFE Secure Campus Architecture Reference Design',
      ard_safe.framework = 'SAFE',
      ard_safe.version   = '1.0',
      ard_safe.filePath  = 'ARD_SAFE_Campus_Reference.md';

MERGE (ard_sda:ARDDocument {docId: 'ARD-SDA-IBN-001'})
  SET ard_sda.title     = 'Cisco SD-Access / IBN Architecture Reference Design',
      ard_sda.framework = 'RFC9315',
      ard_sda.version   = '1.0',
      ard_sda.filePath  = 'ARD_SDA_IBN_Reference.md';

MERGE (v1)-[:REFERENCES_ARD]->(ard_safe);
MERGE (v1)-[:REFERENCES_ARD]->(ard_sda);

// --- Sites ---
MERGE (site_large:Site {siteId: 'SITE-HQ-01'})
  SET site_large.name           = 'Headquarters Campus',
      site_large.siteType       = 'LARGE_CAMPUS',
      site_large.lifecycleState = 'ACTIVE';

MERGE (site_small:Site {siteId: 'SITE-BR-01'})
  SET site_small.name           = 'Branch Site 1',
      site_small.siteType       = 'SMALL_CAMPUS',
      site_small.lifecycleState = 'ACTIVE';

// --- Topologies ---
MERGE (topo_large:Topology {topologyId: 'TOPO-THREE-TIER'})
  SET topo_large.name     = 'Large Site Three-Tier Architecture',
      topo_large.model    = 'THREE_TIER',
      topo_large.siteType = 'LARGE_CAMPUS';

MERGE (topo_small:Topology {topologyId: 'TOPO-TWO-TIER'})
  SET topo_small.name     = 'Small Site Two-Tier Collapsed Architecture',
      topo_small.model    = 'TWO_TIER_COLLAPSED',
      topo_small.siteType = 'SMALL_CAMPUS';

MERGE (site_large)-[:INSTANCE_OF_TOPOLOGY]->(topo_large);
MERGE (site_small)-[:INSTANCE_OF_TOPOLOGY]->(topo_small);

// --- Topology Layers (for large site) ---
MERGE (l_access:TopologyLayer {layerId: 'LAYER-LARGE-ACCESS'})
  SET l_access.name     = 'ACCESS',
      l_access.function = 'End-user and device connectivity; L2 forwarding; QoS ingress marking; RSTP edge ports';

MERGE (l_dist:TopologyLayer {layerId: 'LAYER-LARGE-DIST'})
  SET l_dist.name     = 'DISTRIBUTION',
      l_dist.function = 'L2 aggregation; VLAN trunking; redundant uplinks to firewall pairs; RSTP root bridge';

MERGE (l_core:TopologyLayer {layerId: 'LAYER-LARGE-CORE'})
  SET l_core.name     = 'CORE',
      l_core.function = 'L3 boundary; VLAN termination; default gateway; inter-zone routing; stateful firewall';

MERGE (l_inet:TopologyLayer {layerId: 'LAYER-LARGE-INET'})
  SET l_inet.name     = 'INTERNET_EDGE',
      l_inet.function = 'Internet connectivity; DMZ hosting; VPN termination; publishing services';

MERGE (l_mgmt:TopologyLayer {layerId: 'LAYER-LARGE-MGMT'})
  SET l_mgmt.name     = 'MANAGEMENT',
      l_mgmt.function = 'Out-of-band management; jump host access; SIEM; audit logging';

MERGE (l_access)-[:BELONGS_TO_TOPOLOGY]->(topo_large);
MERGE (l_dist)-[:BELONGS_TO_TOPOLOGY]->(topo_large);
MERGE (l_core)-[:BELONGS_TO_TOPOLOGY]->(topo_large);
MERGE (l_inet)-[:BELONGS_TO_TOPOLOGY]->(topo_large);
MERGE (l_mgmt)-[:BELONGS_TO_TOPOLOGY]->(topo_large);

// --- VLANs (Population) ---
MERGE (vl_emp:VLAN {vlanId: 100})
  SET vl_emp.name = 'employee', vl_emp.vlanGroup = 'POPULATION',
      vl_emp.description = 'Corporate employees', vl_emp.lifecycleState = 'ACTIVE';

MERGE (vl_voice:VLAN {vlanId: 110})
  SET vl_voice.name = 'voice', vl_voice.vlanGroup = 'POPULATION',
      vl_voice.description = 'IP telephony devices', vl_voice.lifecycleState = 'ACTIVE';

MERGE (vl_video:VLAN {vlanId: 130})
  SET vl_video.name = 'video', vl_video.vlanGroup = 'POPULATION',
      vl_video.description = 'Video collaboration', vl_video.lifecycleState = 'ACTIVE';

MERGE (vl_guest:VLAN {vlanId: 140})
  SET vl_guest.name = 'guest', vl_guest.vlanGroup = 'POPULATION',
      vl_guest.description = 'Guest/visitor access', vl_guest.lifecycleState = 'ACTIVE';

MERGE (vl_iot:VLAN {vlanId: 150})
  SET vl_iot.name = 'iot', vl_iot.vlanGroup = 'POPULATION',
      vl_iot.description = 'IoT and building systems', vl_iot.lifecycleState = 'ACTIVE';

MERGE (vl_ctr:VLAN {vlanId: 160})
  SET vl_ctr.name = 'contractor', vl_ctr.vlanGroup = 'POPULATION',
      vl_ctr.description = 'Contractor/third-party', vl_ctr.lifecycleState = 'ACTIVE';

// --- VLANs (DMZ) ---
MERGE (vl_dns:VLAN {vlanId: 200})
  SET vl_dns.name = 'dmz_dns', vl_dns.vlanGroup = 'DMZ',
      vl_dns.description = 'DNS Services DMZ', vl_dns.lifecycleState = 'ACTIVE';

MERGE (vl_ad:VLAN {vlanId: 210})
  SET vl_ad.name = 'dmz_ad', vl_ad.vlanGroup = 'DMZ',
      vl_ad.description = 'Active Directory DMZ', vl_ad.lifecycleState = 'ACTIVE';

MERGE (vl_file:VLAN {vlanId: 220})
  SET vl_file.name = 'dmz_file', vl_file.vlanGroup = 'DMZ',
      vl_file.description = 'File Services DMZ', vl_file.lifecycleState = 'ACTIVE';

MERGE (vl_pbx:VLAN {vlanId: 240})
  SET vl_pbx.name = 'dmz_pbx', vl_pbx.vlanGroup = 'DMZ',
      vl_pbx.description = 'PBX/Telephony DMZ', vl_pbx.lifecycleState = 'ACTIVE';

MERGE (vl_pub:VLAN {vlanId: 250})
  SET vl_pub.name = 'dmz_publish', vl_pub.vlanGroup = 'DMZ',
      vl_pub.description = 'Publishing DMZ (large site)', vl_pub.lifecycleState = 'ACTIVE';

MERGE (vl_oob:VLAN {vlanId: 999})
  SET vl_oob.name = 'oob_mgmt', vl_oob.vlanGroup = 'MANAGEMENT',
      vl_oob.description = 'Out-of-band management', vl_oob.lifecycleState = 'ACTIVE';

// --- VRFs ---
MERGE (vrf_emp:VRF  {vrfId: 'VRF-EMPLOYEE'})   SET vrf_emp.name  = 'EMPLOYEE';
MERGE (vrf_voice:VRF {vrfId: 'VRF-VOICE'})     SET vrf_voice.name = 'VOICE';
MERGE (vrf_video:VRF {vrfId: 'VRF-VIDEO'})     SET vrf_video.name = 'VIDEO';
MERGE (vrf_guest:VRF {vrfId: 'VRF-GUEST'})     SET vrf_guest.name = 'GUEST';
MERGE (vrf_iot:VRF   {vrfId: 'VRF-IOT'})       SET vrf_iot.name   = 'IOT';
MERGE (vrf_ctr:VRF   {vrfId: 'VRF-CONTRACTOR'}) SET vrf_ctr.name  = 'CONTRACTOR';
MERGE (vrf_oob:VRF   {vrfId: 'VRF-OOB-MGMT'})  SET vrf_oob.name  = 'OOB_MGMT';
MERGE (vrf_dmzi:VRF  {vrfId: 'VRF-DMZ-INFRA'}) SET vrf_dmzi.name = 'DMZ_INFRA';
MERGE (vrf_dmzp:VRF  {vrfId: 'VRF-DMZ-PUB'})   SET vrf_dmzp.name = 'DMZ_PUBLISH';

// VLAN → VRF bindings
MERGE (vl_emp)-[:BOUND_TO]->(vrf_emp);
MERGE (vl_voice)-[:BOUND_TO]->(vrf_voice);
MERGE (vl_video)-[:BOUND_TO]->(vrf_video);
MERGE (vl_guest)-[:BOUND_TO]->(vrf_guest);
MERGE (vl_iot)-[:BOUND_TO]->(vrf_iot);
MERGE (vl_ctr)-[:BOUND_TO]->(vrf_ctr);
MERGE (vl_oob)-[:BOUND_TO]->(vrf_oob);
MERGE (vl_dns)-[:BOUND_TO]->(vrf_dmzi);
MERGE (vl_ad)-[:BOUND_TO]->(vrf_dmzi);
MERGE (vl_file)-[:BOUND_TO]->(vrf_dmzi);
MERGE (vl_pbx)-[:BOUND_TO]->(vrf_dmzi);
MERGE (vl_pub)-[:BOUND_TO]->(vrf_dmzp);

// --- Segments ---
MERGE (seg_emp:Segment  {segmentId: 'SEG-EMPLOYEE'})
  SET seg_emp.name = 'Employee', seg_emp.population = 'EMPLOYEE',
      seg_emp.qosDscp = 0, seg_emp.internetAccess = true, seg_emp.internalAccess = true,
      seg_emp.lifecycleState = 'ACTIVE';

MERGE (seg_voice:Segment {segmentId: 'SEG-VOICE'})
  SET seg_voice.name = 'Voice', seg_voice.population = 'VOICE',
      seg_voice.qosDscp = 46, seg_voice.internetAccess = false, seg_voice.internalAccess = true,
      seg_voice.lifecycleState = 'ACTIVE';

MERGE (seg_video:Segment {segmentId: 'SEG-VIDEO'})
  SET seg_video.name = 'Video', seg_video.population = 'VIDEO',
      seg_video.qosDscp = 34, seg_video.internetAccess = false, seg_video.internalAccess = true,
      seg_video.lifecycleState = 'ACTIVE';

MERGE (seg_guest:Segment {segmentId: 'SEG-GUEST'})
  SET seg_guest.name = 'Guest', seg_guest.population = 'GUEST',
      seg_guest.qosDscp = 0, seg_guest.internetAccess = true, seg_guest.internalAccess = false,
      seg_guest.lifecycleState = 'ACTIVE';

MERGE (seg_iot:Segment {segmentId: 'SEG-IOT'})
  SET seg_iot.name = 'IoT', seg_iot.population = 'IOT',
      seg_iot.qosDscp = 0, seg_iot.internetAccess = false, seg_iot.internalAccess = false,
      seg_iot.lifecycleState = 'ACTIVE';

MERGE (seg_ctr:Segment {segmentId: 'SEG-CONTRACTOR'})
  SET seg_ctr.name = 'Contractor', seg_ctr.population = 'CONTRACTOR',
      seg_ctr.qosDscp = 0, seg_ctr.internetAccess = true, seg_ctr.internalAccess = true,
      seg_ctr.lifecycleState = 'ACTIVE';

// Segment → VLAN bindings
MERGE (seg_emp)-[:MAPPED_TO_VLAN]->(vl_emp);
MERGE (seg_voice)-[:MAPPED_TO_VLAN]->(vl_voice);
MERGE (seg_video)-[:MAPPED_TO_VLAN]->(vl_video);
MERGE (seg_guest)-[:MAPPED_TO_VLAN]->(vl_guest);
MERGE (seg_iot)-[:MAPPED_TO_VLAN]->(vl_iot);
MERGE (seg_ctr)-[:MAPPED_TO_VLAN]->(vl_ctr);

// --- Zones ---
MERGE (z_user:Zone {zoneId: 'ZONE-USER'})
  SET z_user.name = 'User', z_user.type = 'USER',
      z_user.securityLevel = 80, z_user.defaultPolicy = 'DENY';

MERGE (z_guest:Zone {zoneId: 'ZONE-GUEST'})
  SET z_guest.name = 'Guest', z_guest.type = 'GUEST',
      z_guest.securityLevel = 10, z_guest.defaultPolicy = 'DENY';

MERGE (z_iot:Zone {zoneId: 'ZONE-IOT'})
  SET z_iot.name = 'IoT', z_iot.type = 'IOT',
      z_iot.securityLevel = 20, z_iot.defaultPolicy = 'DENY';

MERGE (z_dmzi:Zone {zoneId: 'ZONE-DMZ-INFRA'})
  SET z_dmzi.name = 'DMZ Infrastructure', z_dmzi.type = 'DMZ_INFRA',
      z_dmzi.securityLevel = 50, z_dmzi.defaultPolicy = 'DENY';

MERGE (z_dmzp:Zone {zoneId: 'ZONE-DMZ-PUBLISH'})
  SET z_dmzp.name = 'DMZ Publishing', z_dmzp.type = 'DMZ_PUBLISH',
      z_dmzp.securityLevel = 30, z_dmzp.defaultPolicy = 'DENY';

MERGE (z_inet:Zone {zoneId: 'ZONE-INTERNET'})
  SET z_inet.name = 'Internet', z_inet.type = 'INTERNET',
      z_inet.securityLevel = 0, z_inet.defaultPolicy = 'DENY';

MERGE (z_mgmt:Zone {zoneId: 'ZONE-MGMT'})
  SET z_mgmt.name = 'Management', z_mgmt.type = 'MANAGEMENT',
      z_mgmt.securityLevel = 100, z_mgmt.defaultPolicy = 'DENY';

// Segment → Zone bindings
MERGE (seg_emp)-[:BELONGS_TO_ZONE]->(z_user);
MERGE (seg_voice)-[:BELONGS_TO_ZONE]->(z_user);
MERGE (seg_video)-[:BELONGS_TO_ZONE]->(z_user);
MERGE (seg_guest)-[:BELONGS_TO_ZONE]->(z_guest);
MERGE (seg_iot)-[:BELONGS_TO_ZONE]->(z_iot);
MERGE (seg_ctr)-[:BELONGS_TO_ZONE]->(z_user);

// --- Devices (Large Site Sample) ---
MERGE (acc1:Device {deviceId: 'DEV-HQ-ACC-01'})
  SET acc1.hostname = 'sw-hq-acc-01', acc1.vendor = 'Arista', acc1.model = 'EOS 7050',
      acc1.deviceRole = 'ACCESS_SWITCH', acc1.lifecycleState = 'ACTIVE',
      acc1.haRole = 'STANDALONE';

MERGE (acc2:Device {deviceId: 'DEV-HQ-ACC-02'})
  SET acc2.hostname = 'sw-hq-acc-02', acc2.vendor = 'Arista', acc2.model = 'EOS 7050',
      acc2.deviceRole = 'ACCESS_SWITCH', acc2.lifecycleState = 'ACTIVE',
      acc2.haRole = 'STANDALONE';

MERGE (agg1:Device {deviceId: 'DEV-HQ-AGG-01'})
  SET agg1.hostname = 'sw-hq-agg-01', agg1.vendor = 'Arista', agg1.model = 'EOS 7280',
      agg1.deviceRole = 'AGGREGATION_SWITCH', agg1.lifecycleState = 'ACTIVE',
      agg1.haRole = 'ACTIVE_ACTIVE_MEMBER';

MERGE (agg2:Device {deviceId: 'DEV-HQ-AGG-02'})
  SET agg2.hostname = 'sw-hq-agg-02', agg2.vendor = 'Arista', agg2.model = 'EOS 7280',
      agg2.deviceRole = 'AGGREGATION_SWITCH', agg2.lifecycleState = 'ACTIVE',
      agg2.haRole = 'ACTIVE_ACTIVE_MEMBER';

MERGE (usf1:Device {deviceId: 'DEV-HQ-USF-01'})
  SET usf1.hostname = 'fw-hq-usr-01', usf1.vendor = 'Fortinet', usf1.model = 'FortiGate 2600F',
      usf1.deviceRole = 'USER_FW', usf1.lifecycleState = 'ACTIVE',
      usf1.haRole = 'ACTIVE_ACTIVE_MEMBER';

MERGE (usf2:Device {deviceId: 'DEV-HQ-USF-02'})
  SET usf2.hostname = 'fw-hq-usr-02', usf2.vendor = 'Fortinet', usf2.model = 'FortiGate 2600F',
      usf2.deviceRole = 'USER_FW', usf2.lifecycleState = 'ACTIVE',
      usf2.haRole = 'ACTIVE_ACTIVE_MEMBER';

MERGE (dmzfw1:Device {deviceId: 'DEV-HQ-DMZFW-01'})
  SET dmzfw1.hostname = 'fw-hq-dmz-01', dmzfw1.vendor = 'Fortinet', dmzfw1.model = 'FortiGate 2600F',
      dmzfw1.deviceRole = 'DMZ_FW', dmzfw1.lifecycleState = 'ACTIVE',
      dmzfw1.haRole = 'ACTIVE_ACTIVE_MEMBER';

MERGE (dmzfw2:Device {deviceId: 'DEV-HQ-DMZFW-02'})
  SET dmzfw2.hostname = 'fw-hq-dmz-02', dmzfw2.vendor = 'Fortinet', dmzfw2.model = 'FortiGate 2600F',
      dmzfw2.deviceRole = 'DMZ_FW', dmzfw2.lifecycleState = 'ACTIVE',
      dmzfw2.haRole = 'ACTIVE_ACTIVE_MEMBER';

// Device → Site
MERGE (acc1)-[:LOCATED_AT]->(site_large);
MERGE (acc2)-[:LOCATED_AT]->(site_large);
MERGE (agg1)-[:LOCATED_AT]->(site_large);
MERGE (agg2)-[:LOCATED_AT]->(site_large);
MERGE (usf1)-[:LOCATED_AT]->(site_large);
MERGE (usf2)-[:LOCATED_AT]->(site_large);
MERGE (dmzfw1)-[:LOCATED_AT]->(site_large);
MERGE (dmzfw2)-[:LOCATED_AT]->(site_large);

// Device → TopologyLayer
MERGE (acc1)-[:IN_LAYER]->(l_access);
MERGE (acc2)-[:IN_LAYER]->(l_access);
MERGE (agg1)-[:IN_LAYER]->(l_dist);
MERGE (agg2)-[:IN_LAYER]->(l_dist);
MERGE (usf1)-[:IN_LAYER]->(l_core);
MERGE (usf2)-[:IN_LAYER]->(l_core);
MERGE (dmzfw1)-[:IN_LAYER]->(l_inet);
MERGE (dmzfw2)-[:IN_LAYER]->(l_inet);

// --- Firewall Pairs ---
MERGE (fwp_usr:FirewallPair {pairId: 'FWPAIR-HQ-USF'})
  SET fwp_usr.name = 'HQ User Services Firewall Pair',
      fwp_usr.function = 'USER_SERVICES',
      fwp_usr.haModel = 'ACTIVE_ACTIVE',
      fwp_usr.failoverTime = 0,
      fwp_usr.lifecycleState = 'ACTIVE';

MERGE (fwp_dmz:FirewallPair {pairId: 'FWPAIR-HQ-DMZ'})
  SET fwp_dmz.name = 'HQ DMZ/Internet Firewall Pair',
      fwp_dmz.function = 'DMZ_INTERNET',
      fwp_dmz.haModel = 'ACTIVE_ACTIVE',
      fwp_dmz.failoverTime = 0,
      fwp_dmz.lifecycleState = 'ACTIVE';

MERGE (usf1)-[:MEMBER_OF_PAIR]->(fwp_usr);
MERGE (usf2)-[:MEMBER_OF_PAIR]->(fwp_usr);
MERGE (dmzfw1)-[:MEMBER_OF_PAIR]->(fwp_dmz);
MERGE (dmzfw2)-[:MEMBER_OF_PAIR]->(fwp_dmz);


// =============================================================================
// SECTION 5 — EXAMPLE: Intent & Closed-Loop Nodes
// =============================================================================

// Intent: Guest isolation
MERGE (i1:Intent {intentId: 'INT-001'})
  SET i1.statement  = 'Guest devices must not access any internal resource or segment',
      i1.type       = 'SECURITY',
      i1.priority   = 1,
      i1.status     = 'ACTIVE',
      i1.createdAt  = datetime('2025-12-01T00:00:00Z');

// Intent: Voice QoS
MERGE (i2:Intent {intentId: 'INT-002'})
  SET i2.statement  = 'Voice traffic must have end-to-end DSCP EF marking and strict priority queuing',
      i2.type       = 'PERFORMANCE',
      i2.priority   = 1,
      i2.status     = 'ACTIVE',
      i2.createdAt  = datetime('2025-12-01T00:00:00Z');

// Intent Translation for INT-001
MERGE (it1:IntentTranslation {translationId: 'ITRANS-001'})
  SET it1.policyType        = 'FIREWALL_RULE',
      it1.translatedAt      = datetime('2025-12-10T00:00:00Z'),
      it1.translatedBy      = 'SYSTEM',
      it1.translationStatus = 'DEPLOYED';

MERGE (i1)-[:TRANSLATED_TO]->(it1);

// Generated Policy
MERGE (pol1:Policy {policyId: 'POL-USF-GUEST-DENY'})
  SET pol1.name           = 'Guest Zone Isolation Policy',
      pol1.type           = 'FIREWALL_ZONE_POLICY',
      pol1.lifecycleState = 'ACTIVE',
      pol1.lastModified   = datetime('2025-12-10T00:00:00Z');

MERGE (it1)-[:GENERATES_POLICY]->(pol1);
MERGE (pol1)-[:APPLIED_TO]->(usf1);
MERGE (pol1)-[:APPLIED_TO]->(usf2);
MERGE (pol1)-[:GOVERNS]->(seg_guest);


// =============================================================================
// SECTION 6 — OPERATIONAL QUERIES
// Ready-to-run Cypher queries for each lifecycle phase
// =============================================================================

// --- DESIGN: Compliance Gap Analysis ---
// Find requirements not satisfied by any design decision
// MATCH (r:ComplianceRequirement)
// WHERE NOT (r)<-[:SATISFIES]-(:DesignDecision)
// RETURN r.reqId, r.category, r.statement
// ORDER BY r.category;

// --- DESIGN: Unmitigated Threats ---
// Find threat vectors with no mitigating security capability deployed
// MATCH (t:ThreatVector)
// WHERE NOT (t)-[:MITIGATED_BY]->(:SecurityCapability)-[:ENFORCED_BY]->(:Device {lifecycleState: 'ACTIVE'})
// RETURN t.threatId, t.name, t.description;

// --- DEPLOYMENT: Pending Commissioning ---
// Devices in DEPLOYING state not yet commissioned
// MATCH (d:Device {lifecycleState: 'DEPLOYING'})
// WHERE NOT (d)<-[:COMMISSIONED_BY]-(:CommissioningRecord)
// RETURN d.deviceId, d.hostname, d.deviceRole;

// --- OPERATIONS: Non-Compliant Intents ---
// MATCH (i:Intent {status: 'ACTIVE'})
// OPTIONAL MATCH (ar:AssuranceResult)-[:ASSURES]->(i)
// WITH i, ar ORDER BY ar.timestamp DESC LIMIT 1
// WHERE ar.compliance IN ['NON_COMPLIANT', 'DEGRADED']
// RETURN i.intentId, i.statement, ar.compliance, ar.score, ar.timestamp;

// --- OPERATIONS: Config Drift Detection ---
// MATCH (d:Device {lifecycleState: 'ACTIVE'})-[:HAS_CONFIG]->(c:ConfigurationVersion)
// WHERE c.approved = false
// RETURN d.hostname, d.deviceRole, c.capturedAt, c.hash ORDER BY c.capturedAt DESC;

// --- TROUBLESHOOTING: Blast Radius ---
// MATCH (d:Device {hostname: 'sw-hq-acc-01'})
// OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v:VLAN)<-[:MAPPED_TO_VLAN]-(s:Segment)
// OPTIONAL MATCH (s)<-[:COVERS]-(sla:SLA)
// OPTIONAL MATCH (d)-[:LOCATED_AT]->(site:Site)
// RETURN d.hostname,
//        collect(DISTINCT v.name)   AS impactedVLANs,
//        collect(DISTINCT s.name)   AS impactedSegments,
//        collect(DISTINCT sla.name) AS atRiskSLAs,
//        site.name AS site;

// --- TROUBLESHOOTING: Root Cause Chain ---
// MATCH (inc:Incident {incidentId: 'INC-2026-042'})
//       -[:HAS_ROOT_CAUSE]->(rca:RootCause)
//       -[:CAUSED_BY]->(cfg:ConfigurationVersion)
//       -[:PRECEDED_BY*1..5]->(prev:ConfigurationVersion)
// RETURN inc.title, rca.category, cfg.capturedAt, collect({ts: prev.capturedAt, hash: prev.hash}) AS history;

// --- UPGRADE: Zero-Downtime Validation ---
// Verify each segment has ≥2 active devices during migration
// MATCH (seg:Segment)-[:MAPPED_TO_VLAN]->(v:VLAN)
// MATCH (d:Device)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v)
// WHERE d.lifecycleState IN ['ACTIVE', 'DEPLOYING']
// WITH seg, v, collect(d) AS devices
// WHERE size(devices) < 2
// RETURN seg.name, v.name, size(devices) AS deviceCount, 'RISK: Single point of failure' AS warning;

// --- UPGRADE: Architecture Version Delta ---
// MATCH (v2:ArchitectureVersion {version: '2.0.0'})-[:PRECEDED_BY]->(v1:ArchitectureVersion {version: '1.0.0'})
// MATCH (v2)-[:CONTAINS_DECISION]->(d2:DesignDecision)
// WHERE NOT (v1)-[:CONTAINS_DECISION]->(d2)
// RETURN d2.decisionId, d2.title, d2.decision, d2.rationale;

// --- DECOMMISSIONING: Dependency Blocker Check ---
// MATCH (d:Device {hostname: 'fw-hq-usr-01'})
// MATCH (d)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v:VLAN)<-[:MAPPED_TO_VLAN]-(seg:Segment)
// WITH seg, v,
//      count { MATCH (other:Device)-[:HAS_INTERFACE]->(:Interface)-[:CARRIES_VLAN]->(v)
//              WHERE other.lifecycleState = 'ACTIVE' AND other.deviceId <> d.deviceId } AS otherActive
// WHERE otherActive = 0
// RETURN seg.name, v.name, 'BLOCKER: No redundant device for this VLAN' AS status;

// --- LIFECYCLE AUDIT TRAIL ---
// Full history of a device through lifecycle phases
// MATCH (d:Device {hostname: 'sw-hq-acc-01'})
// MATCH (d)-[:IN_PHASE]->(phase:LifecyclePhase)
// OPTIONAL MATCH (phase)<-[:FROM_PHASE|TO_PHASE]-(t:LifecycleTransition)-[:PERFORMED_BY]->(op:Operator)
// RETURN d.hostname, phase.name, t.timestamp, t.reason, op.name ORDER BY t.timestamp ASC;
