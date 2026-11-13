"""The reviewed repositories used for both RPM lock resolution and admission."""
import configparser
import hashlib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'artifacts/ubi.repo'
RPM_ARCH = {'amd64': 'x86_64', 'arm64': 'aarch64'}


def repositories(arch, path=CONFIG):
    rpm_arch = RPM_ARCH[arch]
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(path.read_text())
    if set(config.sections()) != {'baseos', 'appstream'} or config.defaults():
        raise ValueError('missing or unexpected UBI repositories')
    result = {}
    for name in config.sections():
        entry = config[name]
        if entry.getboolean('enabled') is not True or entry.getboolean('gpgcheck') is not True:
            raise ValueError('UBI repositories must be enabled with signature checking')
        url = entry['baseurl'].replace('$basearch', rpm_arch)
        if url != f'https://cdn-ubi.redhat.com/content/public/ubi/dist/ubi9/9/{rpm_arch}/{name}/os/':
            raise ValueError('unexpected UBI repository URL')
        result[name] = url
    return result


def configure(base, tmp, arch):
    import dnf.repo

    urls = repositories(arch)
    for name in ['root', 'cache', 'persist']:
        Path(tmp, name).mkdir()
    base.conf.installroot = tmp + '/root'
    base.conf.cachedir = tmp + '/cache'
    base.conf.logdir = tmp
    base.conf.persistdir = tmp + '/persist'
    base.conf.reposdir = []  # Never load the host's repositories or installed RPMs.
    base.conf.install_weak_deps = False
    base.conf.arch = RPM_ARCH[arch]
    base.conf.ignorearch = True
    base.conf.substitutions.update(arch=RPM_ARCH[arch], basearch=RPM_ARCH[arch], releasever='9')
    base.conf.module_platform_id = 'platform:el9'
    for name, url in urls.items():
        repo = dnf.repo.Repo(name, base.conf)
        repo.baseurl = [url]
        repo.gpgcheck = True
        repo.skip_if_unavailable = False
        repo.metadata_expire = 0
        repo.timeout = 30
        repo.retries = 1
        base.repos.add(repo)
    base.fill_sack(load_system_repo=False)
    for name in urls:
        if not base.sack.query().available().filter(reponame=name):
            raise ValueError(f'missing or empty UBI repository: {name}')
    return {'config_sha256': hashlib.sha256(CONFIG.read_bytes()).hexdigest(), 'urls': urls}
