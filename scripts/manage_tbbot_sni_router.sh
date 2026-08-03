#!/usr/bin/env bash
# Transactional TLS-SNI router for tbbot.duckdns.org and amnezia-xray.

set -euo pipefail

COMMAND="${1:-}"
SNAPSHOT="${2:-}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="tbbot.duckdns.org"
PUBLIC_IP="188.137.236.73"
CONTAINER="amnezia-xray"
EXPECTED_XRAY_IMAGE="sha256:c9b46cda4211c9e3182e3f60076c7047b9825f071b053a3b74354094764b314c"
BACKUP_ROOT="/var/backups/tbbot-sni-router"
LOCK_FILE="/run/lock/tbbot-sni-router.lock"
STREAM_TEMPLATE="${PROJECT_DIR}/deploy/mini-app/nginx-stream-sni.conf.template"
HTTPS_TEMPLATE="${PROJECT_DIR}/deploy/mini-app/nginx-mini-app-https.conf.template"
STREAM_CONFIG="/etc/nginx/stream-conf.d/tbbot-sni-router.conf"
HTTPS_CONFIG="/etc/nginx/sites-available/tb-mini-app-https"
HTTPS_ENABLED="/etc/nginx/sites-enabled/tb-mini-app-https"
STREAM_INCLUDE="/etc/nginx/tbbot-stream.conf"
ACME_WEBROOT="/var/www/letsencrypt"
ROLLBACK_UNIT="tbbot-sni-auto-rollback"
EXPECTED_FRONTEND="/var/www/tb-mini-app/current/index.html"

fail() { echo "ERROR: $*" >&2; exit 1; }
require_root() { [[ "${EUID}" -eq 0 ]] || fail "run as root"; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }
require_snapshot() {
  [[ -n "${SNAPSHOT}" && "${SNAPSHOT}" == "${BACKUP_ROOT}/"* && -d "${SNAPSHOT}" ]] || fail "invalid snapshot path"
}

exec 9>"${LOCK_FILE}"
flock -n 9 || fail "another SNI router operation is running"

resolved_ipv4() { getent ahostsv4 "${DOMAIN}" | awk '{print $1}' | sort -u; }
port_is_free() { ! ss -lntH "sport = :$1" | grep -q .; }

xray_public_summary() {
  docker exec "${CONTAINER}" cat /opt/amnezia/xray/server.json | python3 -c '
import json,sys
d=json.load(sys.stdin)
for i in d.get("inbounds",[]):
    if i.get("port") != 443: continue
    s=i.get("streamSettings") or {}; r=s.get("realitySettings") or {}
    print("protocol="+str(i.get("protocol")))
    print("transport="+str(s.get("network") or "tcp"))
    print("listen="+str(i.get("listen") or "0.0.0.0"))
    print("port=443")
    print("serverNames="+",".join(r.get("serverNames") or []))
    print("dest="+str(r.get("dest") or ""))
'
}

assert_no_sni_conflict() {
  local names
  names="$(docker exec "${CONTAINER}" cat /opt/amnezia/xray/server.json | python3 -c '
import json,sys
d=json.load(sys.stdin)
for i in d.get("inbounds",[]):
    if i.get("port") == 443:
        print("\n".join(((i.get("streamSettings") or {}).get("realitySettings") or {}).get("serverNames") or []))
')"
  ! grep -Fxq "${DOMAIN}" <<<"${names}" || fail "${DOMAIN} is already an Xray Reality serverName"
}

detect_container_source() {
  local compose_workdir compose_files
  compose_workdir="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "${CONTAINER}" 2>/dev/null || true)"
  compose_files="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "${CONTAINER}" 2>/dev/null || true)"
  [[ "${compose_workdir}" != "<no value>" ]] || compose_workdir=""
  [[ "${compose_files}" != "<no value>" ]] || compose_files=""
  if [[ -n "${compose_workdir}" && -n "${compose_files}" ]]; then
    [[ -d "${compose_workdir}" ]] || fail "Compose working directory is missing"
    printf 'compose:%s:%s\n' "${compose_workdir}" "${compose_files}"
    return
  fi
  [[ -f /opt/amnezia/amnezia-xray/Dockerfile ]] || fail "no canonical Compose or Amnezia source"
  # This installation keeps Xray state in the container layer. The exact source
  # is therefore a paused docker commit plus the complete inspect document.
  printf 'inspect-snapshot:/opt/amnezia/amnezia-xray/Dockerfile\n'
}

preflight() {
  require_root
  for cmd in docker nginx systemctl ss getent python3 sha256sum openssl curl flock; do require_command "${cmd}"; done
  [[ "$(resolved_ipv4)" == *"${PUBLIC_IP}"* ]] || fail "DNS does not resolve ${DOMAIN} to ${PUBLIC_IP}"
  systemctl is-active --quiet nginx || fail "Nginx is not active"
  nginx -V 2>&1 | grep -Eq -- '--with-stream(=dynamic)?|ngx_stream_module' || \
    [[ -e /usr/lib/nginx/modules/ngx_stream_module.so ]] || fail "Nginx stream module is unavailable"
  docker inspect "${CONTAINER}" >/dev/null 2>&1 || fail "container ${CONTAINER} is missing"
  [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}")" == true ]] || fail "Xray container is not running"
  [[ "$(docker inspect -f '{{.Image}}' "${CONTAINER}")" == "${EXPECTED_XRAY_IMAGE}" ]] || fail "Xray image digest changed"
  docker port "${CONTAINER}" 443/tcp | grep -Eq '(^|:)443$' || fail "Xray does not publish container TCP 443"
  ! systemctl is-active --quiet "${ROLLBACK_UNIT}.timer" || fail "an automatic rollback timer is already active"
  detect_container_source
  assert_no_sni_conflict
  for port in 8443 2443 18080; do port_is_free "${port}" || fail "loopback target port ${port} is already in use"; done
  [[ -r "${EXPECTED_FRONTEND}" ]] || fail "frontend release is missing"
  [[ -r "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]] || fail "TLS certificate is missing"
  openssl x509 -checkend 86400 -noout -in "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" >/dev/null || fail "TLS certificate is expired or near expiry"
  openssl x509 -checkhost "${DOMAIN}" -noout -in "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" >/dev/null || fail "TLS certificate does not match ${DOMAIN}"
  [[ "$(df -Pk /opt | awk 'NR==2 {print $4}')" -ge 1048576 ]] || fail "less than 1 GiB free on /opt"
  [[ "$(df -Pi /opt | awk 'NR==2 {print $4}')" -ge 5000 ]] || fail "fewer than 5000 inodes free on /opt"
  echo "Preflight: OK"
  echo "Container source: $(detect_container_source)"
  xray_public_summary
}

write_manifest() {
  local snapshot="$1"
  (cd "${snapshot}" && find payload -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
  chmod 0600 "${snapshot}/SHA256SUMS"
}

verify_manifest() {
  local snapshot="$1"
  (cd "${snapshot}" && sha256sum --check --strict SHA256SUMS >/dev/null)
}

prepare() {
  local timestamp snapshot image_ref source
  preflight
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  snapshot="${BACKUP_ROOT}/${timestamp}"
  install -d -o root -g root -m 0700 "${BACKUP_ROOT}" "${snapshot}" "${snapshot}/payload" "${snapshot}/logs"
  source="$(detect_container_source)"
  docker inspect "${CONTAINER}" >"${snapshot}/payload/container-inspect.json"
  docker image inspect "$(docker inspect -f '{{.Image}}' "${CONTAINER}")" >"${snapshot}/payload/image-inspect.json"
  docker ps --no-trunc >"${snapshot}/payload/docker-ps.txt"
  docker port "${CONTAINER}" >"${snapshot}/payload/docker-ports.txt"
  printf '%s\n' "${source}" >"${snapshot}/payload/container-source.txt"
  image_ref="tbbot-sni-snapshot:${timestamp,,}"
  docker commit --pause=true "${CONTAINER}" "${image_ref}" >/dev/null
  printf '%s\n' "${image_ref}" >"${snapshot}/payload/container-image-ref.txt"
  cp -a /opt/amnezia/amnezia-xray "${snapshot}/payload/amnezia-source"
  docker cp "${CONTAINER}:/opt/amnezia/xray/server.json" "${snapshot}/payload/xray-server.json"
  install -d -m 0700 "${snapshot}/payload/nginx" "${snapshot}/payload/certbot"
  cp -a /etc/nginx/. "${snapshot}/payload/nginx/"
  [[ ! -d /etc/letsencrypt ]] || cp -a /etc/letsencrypt/. "${snapshot}/payload/certbot/"
  find /etc/nginx/sites-enabled -maxdepth 1 -printf '%P -> %l\n' >"${snapshot}/payload/nginx-enabled.txt"
  ufw status verbose >"${snapshot}/payload/ufw-status.txt" 2>&1 || true
  ss -lntp >"${snapshot}/payload/ss-lntp.txt"
  systemctl status nginx docker --no-pager --full >"${snapshot}/payload/systemd-status.txt" 2>&1 || true
  systemctl is-active nginx >"${snapshot}/payload/nginx-was-active.txt" || true
  systemctl show fvg-alert-bot -p ActiveState -p SubState -p NRestarts >"${snapshot}/payload/bot-state.txt"
  sha256sum /etc/fvg-alert-bot.env >"${snapshot}/payload/bot-env.sha256"
  cat >"${snapshot}/payload/rollback-plan.txt" <<EOF
1. Disable the Nginx stream listener.
2. Restore /etc/nginx from payload/nginx.
3. Recreate ${CONTAINER} from payload/container-inspect.json and the committed snapshot image.
4. Restore the original host port bindings, networks, capabilities and restart policy.
5. Verify external TCP 443 and the container state.
EOF
  find "${snapshot}" -type d -exec chmod 0700 {} +
  find "${snapshot}" -type f -exec chmod 0600 {} +
  write_manifest "${snapshot}"
  printf '%s\n' "${snapshot}" >"${BACKUP_ROOT}/latest"
  chmod 0600 "${BACKUP_ROOT}/latest"
  echo "Snapshot: ${snapshot}"
  echo "SHA-256 manifest: ${snapshot}/SHA256SUMS"
}

recreate_container() {
  local snapshot="$1" mode="$2"
  python3 - "${snapshot}" "${mode}" <<'PY'
import json, pathlib, shutil, subprocess, sys, tempfile, uuid
snap=pathlib.Path(sys.argv[1]); mode=sys.argv[2]
d=json.loads((snap/'payload/container-inspect.json').read_text())[0]
cfg=d['Config']; host=d['HostConfig']; name=d['Name'].lstrip('/')
payload_image=(snap/'payload/container-image-ref.txt').read_text().strip()
image=d['Image']
if host.get('NetworkMode') not in ('bridge','default'):
    raise SystemExit('unsupported NetworkMode: '+str(host.get('NetworkMode')))
if d.get('Mounts'):
    raise SystemExit('mounted containers require canonical Compose; refusing recreation')
cmd=['docker','create','--name',name]
rp=(host.get('RestartPolicy') or {}).get('Name')
if rp: cmd += ['--restart',rp]
if host.get('Privileged'): cmd += ['--privileged']
if host.get('ReadonlyRootfs'): cmd += ['--read-only']
for cap in host.get('CapAdd') or []: cmd += ['--cap-add',cap]
for cap in host.get('CapDrop') or []: cmd += ['--cap-drop',cap]
for key,val in (host.get('Sysctls') or {}).items(): cmd += ['--sysctl',f'{key}={val}']
for item in host.get('SecurityOpt') or []: cmd += ['--security-opt',item]
for item in host.get('Dns') or []: cmd += ['--dns',item]
log_config=host.get('LogConfig') or {}
if log_config.get('Type'): cmd += ['--log-driver',log_config['Type']]
for key,val in (log_config.get('Config') or {}).items(): cmd += ['--log-opt',f'{key}={val}']
for item in cfg.get('Env') or []: cmd += ['--env',item]
if cfg.get('User'): cmd += ['--user',cfg['User']]
if cfg.get('WorkingDir'): cmd += ['--workdir',cfg['WorkingDir']]
entrypoint=cfg.get('Entrypoint') or []
if entrypoint:
    cmd += ['--entrypoint',entrypoint[0]]
bindings=host.get('PortBindings') or {}
for container_port, entries in bindings.items():
    for entry in entries or []:
        hp=entry.get('HostPort',''); hi=entry.get('HostIp','')
        if container_port == '443/tcp' and mode == 'sni': hi,hp='127.0.0.1','2443'
        spec=f'{hi+":" if hi else ""}{hp}:{container_port}'
        cmd += ['--publish',spec]
cmd += [image]
cmd += entrypoint[1:]
cmd += cfg.get('Cmd') or []
subprocess.run(['docker','rm','-f',name],check=False,stdout=subprocess.DEVNULL)
subprocess.run(cmd,check=True)
seed=f'tbbot-sni-seed-{uuid.uuid4().hex[:12]}'
payload_dir=pathlib.Path(tempfile.mkdtemp(prefix='tbbot-sni-payload.',dir='/var/tmp'))
payload_dir.chmod(0o700)
try:
    subprocess.run(['docker','create','--name',seed,payload_image],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','cp',f'{seed}:/opt/amnezia/.',str(payload_dir)],check=True)
    subprocess.run(['docker','cp',str(payload_dir)+'/.',f'{name}:/opt/amnezia/'],check=True)
finally:
    subprocess.run(['docker','rm','-f',seed],check=False,stdout=subprocess.DEVNULL)
    shutil.rmtree(payload_dir,ignore_errors=True)
networks=d.get('NetworkSettings',{}).get('Networks',{})
for network,meta in networks.items():
    if network == 'bridge': continue
    connect=['docker','network','connect']
    for alias in meta.get('Aliases') or []:
        if alias and alias != name: connect += ['--alias',alias]
    connect += [network,name]
    subprocess.run(connect,check=True)
# Docker implicitly attaches the default bridge during create. Some Amnezia
# containers deliberately have that network disconnected while HostConfig
# still reports NetworkMode=bridge. Reconcile actual membership to inspect.
actual=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
actual_networks=set(actual.get('NetworkSettings',{}).get('Networks',{}))
for extra in sorted(actual_networks-set(networks)):
    subprocess.run(['docker','network','disconnect',extra,name],check=True)
subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL)
PY
}

install_nginx_configs() {
  install -d -o root -g root -m 0755 /etc/nginx/stream-conf.d "${ACME_WEBROOT}"
  install -o root -g root -m 0644 "${STREAM_TEMPLATE}" "${STREAM_CONFIG}"
  install -o root -g root -m 0644 "${HTTPS_TEMPLATE}" "${HTTPS_CONFIG}"
  ln -sfn "${HTTPS_CONFIG}" "${HTTPS_ENABLED}"
  cat >"${STREAM_INCLUDE}" <<'EOF'
stream {
    include /etc/nginx/stream-conf.d/*.conf;
}
EOF
  chmod 0644 "${STREAM_INCLUDE}"
  grep -Fq 'include /etc/nginx/tbbot-stream.conf;' /etc/nginx/nginx.conf || \
    sed -i '/^events {/i include /etc/nginx/tbbot-stream.conf;' /etc/nginx/nginx.conf
}

issue_certificate() {
  require_root; require_snapshot; verify_manifest "${SNAPSHOT}"
  [[ -n "${LETSENCRYPT_EMAIL:-}" && "${LETSENCRYPT_EMAIL}" == *@*.* && "${LETSENCRYPT_EMAIL}" != "<LETSENCRYPT_EMAIL>" ]] || fail "LETSENCRYPT_EMAIL is missing"
  local http_site="/etc/nginx/sites-available/tb-mini-app"
  [[ -f "${http_site}" ]] || fail "HTTP Mini App site is missing"
  install -d -o root -g root -m 0755 "${ACME_WEBROOT}"
  if ! grep -Fq '/.well-known/acme-challenge/' "${http_site}"; then
    python3 - "${http_site}" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); text=p.read_text()
needle="    server_name tbbot.duckdns.org;\n"
block="""

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type text/plain;
        try_files $uri =404;
    }
"""
if text.count(needle) != 1:
    raise SystemExit("unexpected HTTP Mini App site structure")
p.write_text(text.replace(needle, needle+block, 1))
PY
  fi
  nginx -t
  systemctl reload nginx
  certbot certonly --webroot --webroot-path "${ACME_WEBROOT}" --domain "${DOMAIN}" \
    --email "${LETSENCRYPT_EMAIL}" --agree-tos --non-interactive
  certbot certificates
  openssl x509 -in "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" -noout -subject -issuer -dates
}

rollback() {
  require_root; require_snapshot; verify_manifest "${SNAPSHOT}"
  local rollback_rc=0
  set +e
  # Removing a stream config does not release 443 from already loaded workers.
  # Stop Nginx before restoring Xray's original public port binding.
  systemctl stop nginx || rollback_rc=1
  if ss -lntpH 'sport = :443' | grep -q nginx; then
    echo "ERROR: Nginx did not release external port 443" >&2
    rollback_rc=1
  fi
  rm -f "${STREAM_CONFIG}" "${HTTPS_ENABLED}" "${HTTPS_CONFIG}" "${STREAM_INCLUDE}"
  cp -a "${SNAPSHOT}/payload/nginx/." /etc/nginx/ || rollback_rc=1
  recreate_container "${SNAPSHOT}" original || rollback_rc=1
  nginx -t || rollback_rc=1
  if grep -Fxq active "${SNAPSHOT}/payload/nginx-was-active.txt"; then systemctl start nginx || rollback_rc=1; fi
  docker port "${CONTAINER}" 443/tcp | grep -Eq '(^|:)443$' || rollback_rc=1
  [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null)" == true ]] || rollback_rc=1
  date -u +%FT%TZ >"${SNAPSHOT}/logs/rollback.log"
  chmod 0600 "${SNAPSHOT}/logs/rollback.log"
  set -e
  (( rollback_rc == 0 )) || fail "rollback verification failed"
  systemctl stop "${ROLLBACK_UNIT}.timer" 2>/dev/null || true
  echo "Rollback complete"
}

verify_xray_invariants() {
  local snapshot="$1"
  python3 - "${snapshot}" "${CONTAINER}" <<'PY'
import json, pathlib, subprocess, sys
snapshot=pathlib.Path(sys.argv[1])
old=json.loads((snapshot/'payload/container-inspect.json').read_text())[0]
new=json.loads(subprocess.check_output(['docker','inspect',sys.argv[2]],text=True))[0]
checks={
    'image': old['Image'] == new['Image'],
    'restart_policy': old['HostConfig'].get('RestartPolicy') == new['HostConfig'].get('RestartPolicy'),
    'mounts': old.get('Mounts') == new.get('Mounts'),
    'networks': sorted(old.get('NetworkSettings',{}).get('Networks',{})) == sorted(new.get('NetworkSettings',{}).get('Networks',{})),
    'network_mode': old['HostConfig'].get('NetworkMode') == new['HostConfig'].get('NetworkMode'),
    'capabilities': old['HostConfig'].get('CapAdd') == new['HostConfig'].get('CapAdd'),
    'privileged': old['HostConfig'].get('Privileged') == new['HostConfig'].get('Privileged'),
    'security_options': old['HostConfig'].get('SecurityOpt') == new['HostConfig'].get('SecurityOpt'),
    'log_config': old['HostConfig'].get('LogConfig') == new['HostConfig'].get('LogConfig'),
    'dns': (old['HostConfig'].get('Dns') or []) == (new['HostConfig'].get('Dns') or []),
    'read_only_rootfs': old['HostConfig'].get('ReadonlyRootfs') == new['HostConfig'].get('ReadonlyRootfs'),
    'devices': old['HostConfig'].get('Devices') == new['HostConfig'].get('Devices'),
    'sysctls': old['HostConfig'].get('Sysctls') == new['HostConfig'].get('Sysctls'),
}
bindings=new['HostConfig'].get('PortBindings') or {}
checks['xray_mapping'] = bindings.get('443/tcp') == [{'HostIp':'127.0.0.1','HostPort':'2443'}]
failed=[name for name,ok in checks.items() if not ok]
if failed:
    raise SystemExit('Xray invariant mismatch: '+','.join(failed))
print('Xray invariants: OK')
PY
}

verify() {
  require_root; require_snapshot; verify_manifest "${SNAPSHOT}"
  nginx -t
  [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}")" == true ]] || fail "Xray is not running"
  [[ "$(docker inspect -f '{{.Image}}' "${CONTAINER}")" == "${EXPECTED_XRAY_IMAGE}" ]] || fail "Xray image digest changed"
  verify_xray_invariants "${SNAPSHOT}"
  ss -lntH 'sport = :2443' | grep -q '127.0.0.1:2443' || fail "Xray loopback port is unavailable"
  ss -lntH 'sport = :8443' | grep -q '127.0.0.1:8443' || fail "Mini App HTTPS listener is unavailable"
  ss -lntH 'sport = :443' | grep -q ':443' || fail "external 443 is unavailable"
  ss -lntpH 'sport = :443' | grep -q 'nginx' || fail "external 443 is not owned by Nginx"
  ! ss -lntH 'sport = :18080' | grep -q . || fail "Mini App backend must remain disabled"
  curl --resolve "${DOMAIN}:443:127.0.0.1" --fail --show-error --silent "https://${DOMAIN}/" -o /dev/null
  openssl x509 -checkend 86400 -noout -in "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
  timeout 5 bash -c '</dev/tcp/127.0.0.1/2443' || fail "Xray TCP listener is unreachable"
  systemctl is-active --quiet fvg-alert-bot || fail "production bot is not active"
  systemctl is-active --quiet doh-socks-files.service || fail "doh-socks-files.service is not active"
  ss -lntH 'sport = :8080' | grep -q "${PUBLIC_IP}:8080" || fail "protected port 8080 changed"
  (cd "${SNAPSHOT}" && sha256sum --check --strict payload/bot-env.sha256 >/dev/null) || fail "production env changed"
  diff -u "${SNAPSHOT}/payload/bot-state.txt" <(systemctl show fvg-alert-bot -p ActiveState -p SubState -p NRestarts) >/dev/null || fail "production bot state changed"
  echo "Verification: OK"
}

apply() {
  require_root; require_snapshot; verify_manifest "${SNAPSHOT}"
  local deadline rc=0
  deadline="$(date -u -d '+30 minutes' +%FT%TZ)"
  systemd-run --unit="${ROLLBACK_UNIT}" --on-active=30m \
    "$(readlink -f "$0")" rollback "${SNAPSHOT}" >/dev/null
  systemctl is-active --quiet "${ROLLBACK_UNIT}.timer" || fail "automatic rollback timer was not armed"
  echo "AUTO ROLLBACK ARMED"
  echo "Snapshot: ${SNAPSHOT}"
  echo "Deadline: ${deadline}"
  echo "Commit command: sudo $(readlink -f "$0") commit ${SNAPSHOT}"
  trap 'rc=$?; if (( rc != 0 )); then rollback; fi; exit $rc' EXIT
  install_nginx_configs
  [[ -r "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]] || fail "certificate is missing"
  recreate_container "${SNAPSHOT}" sni
  ss -lntH 'sport = :2443' | grep -q '127.0.0.1:2443'
  if ss -lntH 'sport = :443' | grep -q .; then
    fail "external port 443 is still occupied before Nginx reload"
  fi
  nginx -t
  systemctl reload nginx
  verify
  trap - EXIT
}

status() {
  require_root; require_snapshot
  systemctl status "${ROLLBACK_UNIT}.timer" --no-pager --full || true
  systemctl is-active nginx || true
  docker inspect -f 'xray={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "${CONTAINER}"
  certbot certificates 2>/dev/null | sed -n "/Certificate Name: ${DOMAIN}/,/Expiry Date:/p"
  ss -lntp | grep -E ':(443|8443|2443|18080)\b' || true
  curl --resolve "${DOMAIN}:443:127.0.0.1" --fail --silent --show-error "https://${DOMAIN}/" -o /dev/null && echo "frontend=https-ok" || true
}

commit_change() {
  require_root; require_snapshot
  verify
  [[ -f "${SNAPSHOT}/vpn-external-confirmed" ]] || fail "external Amnezia/VPN confirmation marker is missing"
  systemctl stop "${ROLLBACK_UNIT}.timer" "${ROLLBACK_UNIT}.service" 2>/dev/null || true
  systemctl reset-failed "${ROLLBACK_UNIT}.service" 2>/dev/null || true
  date -u +%FT%TZ >"${SNAPSHOT}/committed"
  chmod 0600 "${SNAPSHOT}/committed"
  echo "Committed"
}

usage() {
  echo "Usage: sudo $0 {preflight|prepare|certificate|apply|status|verify|commit|rollback} [snapshot]"
}

case "${COMMAND}" in
  preflight) preflight ;;
  prepare) prepare ;;
  certificate) issue_certificate ;;
  apply) apply ;;
  status) status ;;
  verify) verify ;;
  commit) commit_change ;;
  rollback) rollback ;;
  *) usage; exit 2 ;;
esac
