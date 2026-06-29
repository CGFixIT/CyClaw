# Domain-to-Workgroup Migration & Hardening — Master Checklist
Veeam Confidential – Internal Use Only • Validated 2024-06-08
Sources: KB4469 [1], KB3224 [2], bp.veeam.com [3], VBR HelpCenter v12/13 [4]

---

## Phase 1 — Pre-Migration Audit & Preparation
*(3–5 days, depending on infrastructure size)*

### 1.1 Credential & Service-Account Audit
- [ ] Export full list from Veeam **Credentials Manager**.
- [ ] Identify any entries in `.⁠user` format.
- [ ] Convert to **HOSTNAME\user** or **DOMAIN\user**.
- [ ] Run **KB3224** cleanup to remove stale creds.
- [ ] Create local admin (same or mapped name) on:
  - VBR server
  - All Windows proxies
  - All Windows repositories
  - (Optional) identical-name sudo user on each Linux hardened repo
- [ ] Store passwords in corporate vault; avoid identical passwords.
- [ ] VBR Console → Users & Roles → add every local admin explicitly.
- [ ] Test console login with local admin.

⚠️ **[Checkpoint]** Able to open VBR console using local admin only.

### 1.2 Database & Services
- [ ] `services.msc` → confirm all Veeam services run as **LocalSystem**.
  - If any domain account found, switch to **LocalSystem** & restart.
- [ ] Launch **DBConfig** → move Config DB auth to **SQL / PostgreSQL native**.
  - Test connection & restart services.

### 1.3 DNS & Name Resolution (Critical)
- [ ] Create (or verify) **A-record** for VBR hostname in production DNS.
- [ ] NIC → Advanced TCP/IP → DNS tab → add prod domain suffix.
- [ ] Identify Managed Servers registered by FQDN; if required:
  - Plan renaming with **KB1905** or prepare `hosts` file.
- [ ] Record all server IP/FQDN mappings for rollback.

### 1.4 Time Synchronisation
- [ ] Choose external or internal NTP source; document address.
- [ ] Verify `w32tm /query /status` shows correct source.

### 1.5 Guest Interaction / gMSA Review
- [ ] List jobs using **Application-Aware Processing**.
- [ ] Detect **gMSA** usage; if found:
  - Deploy/nominate a **domain-joined Guest Interaction Proxy**.
  - Re-assign affected jobs to that GIP.

### 1.6 SAN / iSCSI & Direct-SAN Prep
- [ ] `iscsicpl.exe` → copy **Initiator IQN** for VBR & each proxy.
- [ ] Notify storage team; schedule allow-list updates post-unjoin.

### 1.7 CDP & ESXi Dependencies
- [ ] List CDP policies; record current VBR registration (FQDN vs IP).
- [ ] Ensure prod DNS holds record for **VBR short name** if CDP uses it.

### 1.8 Backup & Rollback Assets
- [ ] Run an **encrypted Configuration Backup**; copy `.bco` off-box.
- [ ] Snapshot / VM-level backup of the VBR server.
- [ ] Document active Windows Firewall rules (`netsh advfirewall show allprofiles`).

---

## Phase 2 — Domain Unjoin Execution
*(4–8 hours for VBR + ~10 managed hosts)*

### 2.1 Change Order
1. Enterprise Manager (if present)
2. VBR Server
3. Proxies / Repositories / Tape / Veeam ONE / WAN Accel

### 2.2 Unjoin Procedures
- [ ] Disable backup, copy, CDP, and log-truncation jobs (pause scheduling).
- [ ] Log in **as local admin** on each component.
- [ ] System Properties → Change → Workgroup (e.g., **BACKUP**).
- [ ] Provide domain creds to unjoin; reboot.

### 2.3 Immediate Post-Reboot Actions (VBR first)
- [ ] Confirm console login with local admin.
- [ ] Re-run `w32tm` commands to add NTP server; verify sync.
- [ ] Note **new iSCSI IQN**; send to storage team for allow-list update.
- [ ] Windows Credential Manager → remove cached domain creds.

⚠️ **[Checkpoint]** VBR services start; Config DB accessible.

---

## Phase 3 — Credential & Connectivity Re-Binding
*(Same day)*

- [ ] VBR Console → Backup Infrastructure → Managed Servers:
  - Replace stored creds with `HOST\user` or SSH key for Linux.
  - Click **Rescan** for each server; resolve errors.
- [ ] Update SAN allow-lists with new IQNs; test iSCSI logon.
- [ ] Verify Direct-SAN mode proxies show “Ready”.
- [ ] Run `Test-NetConnection <proxy> -Port 6162` (Windows transport).
- [ ] Perform file-level restore test to domain CIFS share; use Windows Credential Manager if necessary.

⚠️ **[Checkpoint]** All managed servers show **Status: Connected**.

---

## Phase 4 — Job Validation & Production Re-Enable
*(2–3 days)*

- [ ] Re-enable jobs **one at a time**; monitor for:
  - VMware VM backup success
  - Hyper-V VM backup success
  - Agent backup success
  - App-aware backup via new GIP
  - Backup Copy & Catalyst Copy to StoreOnce
  - CDP policy test
- [ ] Check logs for **Event ID 190 / 2580** (immutability confirmed).
- [ ] DNS: `nslookup` tests both directions (to/from VBR).

⚠️ **[Checkpoint]** Three consecutive successful job cycles.

---

## Phase 5 — Post-Migration Hardening
*(1–2 days)*

### 5.1 Network Segmentation & Access
- [ ] Move VBR/proxies/repos to dedicated **Backup VLAN**.
- [ ] Restrict inbound RDP; use jump host + standalone Veeam Console.

### 5.2 Console & MFA
- [ ] Enable built-in MFA (v12.1+); remove **BUILTIN\Administrators** role.
- [ ] Add 4-Eyes authorisation (on upgrade to v13).

### 5.3 Immutability & Air-Gap
- [ ] Hardened Linux repo: verify `lsattr` shows `i` flag on backup files.
- [ ] StoreOnce Catalyst: enable **Immutability** & test delete lock.
- [ ] Cloud Bank / SOBR Capacity: Object Lock or Blob Immutability enabled.

### 5.4 Configuration Backup & Password Hygiene
- [ ] Run fresh encrypted config backup; copy to immutable location.
- [ ] Rotate local admin passwords; update vault.

---

## Phase 6 — Monitoring & DR Runbooks
*(≤1 day)*

- [ ] Veeam ONE / Threat Center dashboards for failed jobs & immutability alerts.
- [ ] Enable **Recon Scanner** (if V13) for ransomware indicators.
- [ ] Update DR runbook:
  1. Steps to restore config backup on workgroup VBR.
  2. SAN remap / initiator IQN procedures.
- [ ] Schedule quarterly DR drill & credential rotation.

---

## Critical “Zero-Tolerance” Failure Points

| Task | Verification |
|------|--------------|
| Add local admin role | Console login test pre-unjoin |
| Static DNS A-record | `nslookup vbr-hostname` from domain server |
| DB switched to native auth | DBConfig test connects OK |
| NTP configured | `w32tm /query /status` shows external source |
| SAN allow-list updated | iSCSI session re-established |
| Encrypted config backup | Test restore on isolated VM |

---

## References
1. KB4469 – Impacts of removing Veeam server from a domain
2. KB3224 – How to remove duplicate credentials in Veeam
3. Veeam Security Best Practices – Workgroup vs Domain
4. VBR HelpCenter v12/13 – Users & Roles, DBConfig, Ports, gMSA, Config Backup

---

Need assistance mid-migration?
• Internal Veeam employee IT issues → servicedesk@veeam.com  
• Customer support → support@veeam.com | https://www.veeam.com/kb1771
