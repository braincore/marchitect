from typing import (
    TYPE_CHECKING,
    List,
    Optional,
)

# Hack to avoid circular imports for mypy
if TYPE_CHECKING:
    from .whiteprint import Whiteprint


class Prefab:
    """
    Declarative deployment specifications.

    Requirements:
    - Implement execute() & validate() for default modes:
        install, update, clean, start, stop
    - Idempotent (failures can always be retried)
    """
    def execute(self, whiteprint: 'Whiteprint', mode: str) -> None:
        raise NotImplementedError

    def validate(self, whiteprint: 'Whiteprint', mode: str) -> Optional[str]:
        raise NotImplementedError


class Apt(Prefab):
    def __init__(self, packages: List[str]):
        # TODO: Support packages with version specification.
        assert isinstance(packages, list)
        assert len(packages) > 0
        self.packages = [pkg.lower() for pkg in packages]

    def execute(self, whiteprint: 'Whiteprint', mode: str) -> None:
        if mode == 'install':
            whiteprint.exec('apt install -y %s' % ' '.join(self.packages))

    def validate(self, whiteprint: 'Whiteprint', mode: str) -> Optional[str]:
        if mode == 'install':
            res = whiteprint.exec(
                'apt -qq list %s' % ' '.join(self.packages))
            installed_packages = set()
            for line in res.stdout.decode('utf-8').splitlines():
                installed_package, _ = line.split('/', 1)
                installed_packages.add(installed_package.lower())
            for package in self.packages:
                if package not in installed_packages:
                    return 'Apt package %r missing.' % package
            return None
        else:
            return None


class Pip3(Prefab):
    def __init__(self, packages: List[str]):
        # TODO: Support packages with version specification.
        self.packages = [pkg.lower() for pkg in packages]

    def execute(self, whiteprint: 'Whiteprint', mode: str) -> None:
        if mode == 'install':
            whiteprint.exec('pip3 install %s' % ' '.join(self.packages))

    def validate(self, whiteprint: 'Whiteprint', mode: str) -> Optional[str]:
        if mode == 'install':
            res = whiteprint.exec(
                'pip3 show %s' % ' '.join(self.packages))
            installed_packages = set()
            for line in res.stdout.decode('utf-8').splitlines():
                if line.startswith('Name: '):
                    installed_package = line.split(maxsplit=1)[1]
                    installed_packages.add(installed_package.lower())
            for package in self.packages:
                if package not in installed_packages:
                    return 'Pip3 package %r missing.' % package
            return None
        else:
            return None
