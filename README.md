# Ignition Gateway → GitHub Versioning Setup

A guide for version-controlling Ignition gateway configuration across dev, qa, and
production environments using Git and a three-branch promotion workflow.

## Overview

**Branches:**
- `prod` — production (default branch)
- `qa` — testing/staging
- `dev` — active development

**Workflow:** changes are made on the `dev` gateway, promoted to `qa` for testing, then
promoted to `prod`. Promotions happen via merge/PR on GitHub — qa and prod gateways only
ever `git pull`, they're never edited directly.

**Account model:** each gateway host runs Ignition, and performs all git operations, as
a dedicated `ignition` service account — never as `root` or a personal login. This keeps
file ownership consistent and prevents git operations from breaking Ignition's ability
to read/write its own config files.

**Key model:** each host authenticates to GitHub with its own SSH **deploy key**, scoped
to just this repository. The dev host's key has write access; qa and prod keys are
read-only, since those environments should only ever pull, never push.

---

## 1. Create the service account

On every gateway host, before installing Ignition:

```bash
sudo useradd -r -m -d /home/ignition -s /bin/bash ignition
```

---

## 2. Install Ignition as the `ignition` user

Launch the installer as `root` (e.g. with `sudo`) so it prompts for which user the
gateway service should run as. Specify `ignition` at that prompt.

During installation:
- **Install as a service?** → No — a custom systemd unit is configured in the next step.
- **Start the gateway now?** → No — configuration is reviewed and edited first.

Once installation completes, confirm ownership landed correctly:
```bash
ls -la /usr/local/bin/ignition/data
```
Everything should be owned by `ignition:ignition`.

---

## 3. Generate a deploy key for this host

```bash
sudo -u ignition -H ssh-keygen -t ed25519 -C "<host>-gateway-deploy-key" -f /home/ignition/.ssh/id_ed25519
sudo -u ignition cat /home/ignition/.ssh/id_ed25519.pub
```

Replace `<host>` with `dev`, `qa`, or `prod`.

Add the public key on GitHub under the repository: **Settings → Deploy keys → Add deploy key**

- **dev host:** check "Allow write access"
- **qa host:** leave read-only
- **prod host:** leave read-only

Test the connection:
```bash
sudo -u ignition ssh -T git@github.com
```

---

## 4. Configure Ignition under systemd

`/etc/systemd/system/ignition.service`:
```ini
[Unit]
Description=Ignition Gateway
After=network.target

[Service]
Type=forking
User=ignition
Group=ignition
WorkingDirectory=/usr/local/bin/ignition
ExecStart=/usr/local/bin/ignition/ignition.sh start
ExecStop=/usr/local/bin/ignition/ignition.sh stop
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ignition
sudo systemctl start ignition
sudo systemctl status ignition
```

Confirm the service is `active (running)` before continuing.

---

## 5. Initialize git — dev host only

All git commands are run as the `ignition` user:

```bash
sudo -u ignition -H bash
cd /usr/local/bin/ignition/data

git init
git config user.name "ignition-service"
git config user.email "gateway-service@amarach.io"
git remote add origin git@github.com:thedavidschultz/ignition.git
```

Add a `.gitignore` before the first commit:

```
# Database files
**/db/
**/metricsdb/
**/autobackup/
**/db_backup_sqlite.idb
**/valueStore.idb

# Cache and temporary files
**/jar-cache/
**/request
**/response
*.tmp
*.bak
**/var

# Log files
*.log
**/logs

# Certificates and security
**/certificates/
**/keystore/

# Runtime configuration (environment-specific)
**/config/local
**/config/resources/local

# Gateway-specific runtime files
**/.container-init.conf

# Backup and converted files
**/conversion-report.txt
**.digest.json

# Project conversion artifacts
**/projects/conversion-report.txt
**/migration-log-*.md
**/.resources/

# Alarm history files
**/.alarms_*

# SQLite journal/WAL sidecar files
*.idb-journal
*-wal
*-shm
```

Commit and push, `prod` first so it becomes the default branch automatically on an
empty repository:

```bash
git add .
git commit -m "chore: initial commit"

git branch -M prod
git push -u origin prod

git checkout -b qa
git push -u origin qa

git checkout -b dev
git push -u origin dev

git checkout dev
```

---

## 6. Set up the qa and prod hosts

After steps 1–4 are complete on each host:

```bash
sudo -u ignition -H bash
cd /usr/local/bin/ignition/data

git init
git config user.name "ignition-service"
git config user.email "gateway-service@amarach.io"
git remote add origin git@github.com:thedavidschultz/ignition.git
git fetch origin
git checkout qa      # on the qa host — use "prod" on the prod host
```

The installer creates a few default template files (`gateway.xml_clean`, `ignition.conf`,
`log4j.properties`, `logback.xml`) even without ever starting the service. These will
conflict with the incoming checkout — remove them first, since the versions already
committed from dev will replace them:
```bash
rm gateway.xml_clean ignition.conf log4j.properties logback.xml
git checkout qa      # or "prod"
sudo systemctl restart ignition
sudo systemctl status ignition
```

Each host stays permanently checked out on its own branch.

**Ignition modules are not carried by git.** A module (`.modl` package) has to be
installed manually on each host via Gateway web UI → Config → Modules → Install — the
same way it was installed on dev. Only the *configuration* that depends on a module
(tag providers, connections, projects using that module's resource types) is git-tracked.
If a commit adds configuration for a module that isn't installed yet on qa or prod, the
gateway won't know what to do with those resource types. Always install any new module
on the target host **before** pulling a commit that depends on it.

---

## 7. Day-to-day workflow

**On the dev host** — the only place configuration changes are made:
```bash
git add .
git commit -m "feat(tags): add new UDT for line 3 sensors"
git push origin dev
```

**Promoting dev → qa:** merge via a pull request on GitHub. Once merged:
```bash
# on the qa host
git pull origin qa
sudo systemctl restart ignition
```

**Promoting qa → prod:** same pattern, once testing is complete:
```bash
# on the prod host
git pull origin prod
sudo systemctl restart ignition
```

Since qa and prod deploy keys are read-only, a `git push` from those hosts fails by
design — a deliberate safety net.

---

## 8. Adding a new capability (modules, connections, tag providers)

Installing something new — a module, a database connection, a tag provider — touches
more than git, and the order matters. Follow this sequence rather than treating it as a
plain config promotion:

**1. Install any required modules on all three hosts first, in any order.**
Modules (`.modl` packages) are never carried by git — only the configuration that
depends on them is. Installing modules everywhere up front, before touching git at all,
means the configuration that follows will always find the module it depends on already
in place. Gateway web UI → Config → Modules → Install, on dev, qa, and prod.

**2. Create secrets on all three hosts, each with that environment's own credential.**
Secrets live under `db/`, which is excluded from git entirely — the secret *value*
never travels between hosts, only a *reference* to it does. Create the secret under the
same name on every host (e.g. `KanoaSQL`, not `KanoaDEV`/`KanoaQA`/`KanoaPROD` — see
"Environment-specific settings" below for why), each with its own correct password, via
Config → Security → Secret Providers. Order doesn't matter relative to git, but doing
this before the connection config is promoted means the connection can authenticate the
moment it lands, with no gap.

**3. Build the actual connections, tag providers, and related configuration on dev
only.** Don't pre-create these on qa or prod — since they're git-tracked, a manually-
built version on qa will conflict with the incoming `git checkout` the same way the
installer's template files did (see Step 6). Let git checkout create these structures
from dev's commit instead. Commit and push from dev as usual:
```bash
git add .
git commit -m "feat(gateway): add <capability> database connection and tag provider"
git push origin dev
```

**4. Promote to qa, then prod, following the standard workflow above.** On the first
checkout of a commit containing new resource paths, you may hit the same untracked-file
conflict described in Step 6 if the target host has any pre-existing files at those
paths — remove them first, same as before.

**5. Correct any per-host fields that rode along in the tracked config** — gateway
name, connection endpoint if it's meant to differ, and anything else listed under
"Environment-specific settings" below. Then restart the service.

---

## 9. Commit message convention

```
<type>(<scope>): <short summary>
```

**Types:**
- `feat` — new functionality (tag structure, script, UDT)
- `fix` — correcting a bug or misconfiguration
- `config` — gateway/config changes not tied to a specific feature
- `refactor` — restructuring without changing behavior
- `docs` — documentation-only changes
- `chore` — housekeeping (gitignore, cleanup)

**Scope examples:** `tags`, `projects`, `gateway`, `modules`, `alarms`, `udt`

**Examples:**
```
feat(projects): add Juice Factory lot genealogy scripts
fix(tags): correct assetId key mismatch in transfer script
config(gateway): update redundancy peer settings for qa
chore(gitignore): exclude idb-journal and wal files
```

**Promotion commits** (if merging via CLI rather than PR):
```
Promote dev to qa: <summary>
Promote qa to prod: <summary>
```

---

## 10. Optional safeguards

**Pre-push hook per host** — a trip-wire against pushing from the wrong branch on the
wrong gateway. Not committed to the repo; set up locally on each host as the `ignition`
user.

`/usr/local/bin/ignition/data/.git/hooks/pre-push`:
```bash
#!/bin/bash
expected="dev"   # change to "qa" or "prod" on those hosts
current=$(git rev-parse --abbrev-ref HEAD)
if [ "$current" != "$expected" ]; then
  echo "ERROR: This host should only push from '$expected', but you're on '$current'."
  exit 1
fi
```
```bash
sudo -u ignition chmod +x /usr/local/bin/ignition/data/.git/hooks/pre-push
```

**Branch protection on `prod`** (GitHub → repo Settings → Branches → Add classic branch
protection rule) — worth adding once the workflow stabilizes.

---

## Environment-specific settings to set manually per host

A few values are stored in tracked config files but are genuinely host-specific — they
should be set manually on each host after checkout, not promoted from dev.

**Gateway name.** Stored in `config/resources/core/ignition/system-properties/config.json`
as `systemName`. This file also carries legitimately shared settings (thread dump
thresholds, scheduled backup config, script encoding), so it stays tracked — only the
name itself is set per host, after each checkout:
- Gateway web UI → Config → System → General → Gateway Name

**Redundancy peer settings**, if configured — connection details for the paired gateway
are specific to that host's redundant pair and shouldn't be promoted blindly between
environments. Keep the actual database name identical across
environments (e.g. `kanoaCore` on every SQL Server instance) so the connection config's
`databaseName` property never needs a post-checkout edit. The value that's genuinely
host-specific is `connectURL` — which SQL Server instance a given environment points at.
If dev, qa, and prod ever use separate SQL Server instances rather than a shared one,
check and correct `connectURL` after any promotion that touches a database connection's
config, via Gateway web UI → Config → Databases → Connections → *(connection name)*.

**Secret names should stay environment-agnostic.** A connection's password reference
(`secretName`) is carried forward by git, but the secret's actual *value* is set
independently per host and never syncs — it lives under `db/`, which is excluded from
version control. Use a name like `KanoaSQL` rather than `KanoaDEV`/`KanoaQA`/`KanoaPROD`
so the reference itself never needs editing across promotions; only the value differs,
set once per host via Config → Security → Secret Providers.

As more of these turn up during Kanoa setup or later work, add them here rather than
excluding whole files from git — most config files carry a mix of shared and
host-specific values, and the goal is to promote the shared parts while setting the
host-specific ones by hand.

---

## A note on running commands as `ignition`

The `ignition` service account intentionally has no `sudo` rights — this is by design,
so a pulled config can never be used to escalate to root-level system access. In
practice this means git operations and `systemctl` commands happen in two different
shell contexts:

```bash
# git operations — as ignition
sudo -u ignition -H bash
cd /usr/local/bin/ignition/data
git pull origin qa
exit

# service control — back as your own login
sudo systemctl restart ignition
sudo systemctl status ignition
```

Don't add `ignition` to sudoers to avoid the shell switch — the separation is
intentional.

| Host | Branch | Deploy key access | Typical commands |
|------|--------|--------------------|-------------------|
| dev host  | `dev`  | Read + write | `git add`, `git commit`, `git push origin dev` |
| qa host   | `qa`   | Read only    | `git pull origin qa` |
| prod host | `prod` | Read only    | `git pull origin prod` |

All commands run as the `ignition` service user — never as `root` or a personal login.
