#!/usr/bin/env bash
# Offline admission rechecks the committed manifests, headers and signatures.
set -Eeuo pipefail
arch="${1:?architecture required}"
case "$arch" in amd64|arm64) ;; *) exit 1;; esac
cd /bundle
sha256sum --check "/locks/${arch}.sha256"
test "$(find . -type f | wc -l)" = "$(wc -l < "/locks/${arch}.sha256")"
test -z "$(find . -type l -print -quit)"
mkdir /tmp/rpm-trust
rpm --dbpath /tmp/rpm-trust --import /bundle/keys/*.txt
while IFS=$'\t' read -r filename nevra source_rpm; do
    test "$(rpm -qp --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' "rpms/$filename")" = "$nevra"
    test "$(rpm -qp --qf '%{SOURCERPM}' "rpms/$filename")" = "$source_rpm"
    rpmkeys --dbpath /tmp/rpm-trust --checksig "rpms/$filename" | grep -F 'digests signatures OK'
done < "/locks/${arch}.nevra"
rpm --root /runtime --import /bundle/keys/*.txt
rpm --root /runtime --upgrade --replacepkgs /bundle/rpms/*.rpm
# Python's RPM requires a bootstrap pip wheel. Remove it and ensurepip;
# neither pip nor any other package manager belongs in the final runtime.
rpm --root /runtime --erase --nodeps python3.12-pip-wheel
cp /bundle/wheel/*.whl /runtime/tmp/sail.whl
chroot /runtime /usr/bin/python3.12 -I -B /tmp/install-wheel.py
mkdir -p /runtime/usr/share/licenses/sail /runtime/opt/sail/source /runtime/etc/sail /runtime/var/lib/sail
cp /bundle/source/LICENSE /runtime/usr/share/licenses/sail/LICENSE
cp /bundle/source/Cargo.lock /runtime/opt/sail/source/Cargo.lock
cp /locks/sail.lock.json /runtime/opt/sail/artifact-lock.json
rm -rf /runtime/usr/lib64/python3.12/ensurepip /runtime/usr/lib/python3.12/ensurepip \
    /runtime/etc/yum.repos.d /runtime/etc/dnf /runtime/var/cache/* /runtime/var/log/* \
    /runtime/tmp/* /runtime/var/tmp/* /runtime/run/*
find /runtime -xdev -type f -perm /6000 -exec chmod a-s {} +
printf 'sail:x:10001:10001:Sail:/var/lib/sail:/sbin/nologin\n' >> /runtime/etc/passwd
printf 'sail:x:10001:\n' >> /runtime/etc/group
chown 10001:10001 /runtime/var/lib/sail
chmod 0700 /runtime/var/lib/sail
# No generated private material or credentials are installed.
