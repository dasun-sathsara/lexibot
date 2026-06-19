#!/usr/bin/env bash
# Nightly + pre-deploy snapshot of the Anki collection volume.
# Retains 7 daily + 4 weekly snapshots. Run from the repo root on the VPS.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/lexibot}"
SYNC_VOLUME="${SYNC_VOLUME:-lexibot_anki-sync-data}"
PROFILE_VOLUME="${PROFILE_VOLUME:-lexibot_anki-profile}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DOW="$(date +%u)" # 1..7, 7 = Sunday

mkdir -p "${BACKUP_ROOT}/daily" "${BACKUP_ROOT}/weekly"

snapshot() {
	local volume="$1" label="$2" dest="$3"
	docker run --rm \
		-v "${volume}:/data:ro" \
		-v "${dest}:/backup" \
		alpine:3 \
		tar czf "/backup/${label}-${STAMP}.tar.gz" -C /data .
}

# Daily snapshot of both stateful volumes.
snapshot "${SYNC_VOLUME}" "sync" "${BACKUP_ROOT}/daily"
snapshot "${PROFILE_VOLUME}" "profile" "${BACKUP_ROOT}/daily"

# Promote to weekly on Sundays.
if [ "${DOW}" = "7" ]; then
	cp "${BACKUP_ROOT}/daily/sync-${STAMP}.tar.gz" "${BACKUP_ROOT}/weekly/"
	cp "${BACKUP_ROOT}/daily/profile-${STAMP}.tar.gz" "${BACKUP_ROOT}/weekly/"
fi

# Retention: keep 7 newest daily and 4 newest weekly per prefix.
prune() {
	local dir="$1" keep="$2" prefix="$3"
	ls -1t "${dir}/${prefix}"-*.tar.gz 2>/dev/null | tail -n "+$((keep + 1))" | xargs -r rm -f
}
prune "${BACKUP_ROOT}/daily" 7 sync
prune "${BACKUP_ROOT}/daily" 7 profile
prune "${BACKUP_ROOT}/weekly" 4 sync
prune "${BACKUP_ROOT}/weekly" 4 profile

echo "snapshot complete: ${STAMP}"
