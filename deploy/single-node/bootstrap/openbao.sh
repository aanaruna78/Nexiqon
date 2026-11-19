#!/bin/sh
# OpenBao on one server: file storage in the openbao volume. The first start initialises it with a
# single unseal key and creates the tool gateway's token (policy: the kv mount only). Later starts
# unseal with the stored key, so the server comes back after a reboot. The key sits next to the
# data it protects: sealing does not protect a stolen disk here. Use auto-unseal with an HSM or
# KMS where that matters (README: security).
set -eu
D=/openbao
mkdir -p "$D/data"
cat > "$D/server.hcl" <<HCL
storage "file" { path = "$D/data" }
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true   # internal network only; never published
}
disable_mlock     = true
api_addr          = "http://openbao:8200"
max_lease_ttl     = "87600h"
default_lease_ttl = "768h"
HCL
chown -R openbao:openbao "$D"
rm -f "$D/ready"
su-exec openbao bao server -config="$D/server.hcl" &
SERVER=$!
trap 'kill $SERVER' TERM INT

until bao status >/dev/null 2>&1 || [ $? -eq 2 ]; do sleep 1; done   # 2 = up but sealed
if [ ! -f "$D/init.json" ]; then
  bao operator init -key-shares=1 -key-threshold=1 -format=json > "$D/init.json"
  chmod 600 "$D/init.json"
fi
KEY=$(grep -A1 '"unseal_keys_b64"' "$D/init.json" | tail -1 | tr -d ' ",')
ROOT=$(grep '"root_token"' "$D/init.json" | sed 's/.*: *"\(.*\)".*/\1/')
bao operator unseal "$KEY" >/dev/null

if [ ! -f "$D/tool-gateway.yaml" ]; then
  export BAO_TOKEN="$ROOT"
  bao secrets enable -path=secret -version=2 kv >/dev/null 2>&1 || true
  printf '%s\n' \
    'path "secret/data/*" { capabilities = ["create", "read", "update", "delete"] }' \
    'path "secret/metadata/*" { capabilities = ["read", "list", "delete"] }' \
    | bao policy write tool-gateway - >/dev/null
  TOKEN=$(bao token create -orphan -no-default-policy -policy=tool-gateway -ttl=87600h -field=token)
  umask 022
  printf 'secrets:\n  backend: openbao\n  address: http://openbao:8200\n  mount: secret\n  token: "%s"\n' \
    "$TOKEN" > "$D/tool-gateway.yaml.new"
  mv "$D/tool-gateway.yaml.new" "$D/tool-gateway.yaml"
  unset BAO_TOKEN
fi
touch "$D/ready"
wait $SERVER
