import shlex
from typing import (
    Dict,
    List,
    Optional,
)

import schema  # type: ignore

from .whiteprint import Config, Prefab, Whiteprint


class Apt(Whiteprint):

    cfg_schema = {
        "packages": [schema.And(str, schema.Use(str.lower))],
    }

    def _execute(self, mode: str) -> None:
        if mode == "install":
            self.exec(
                "DEBIAN_FRONTEND=noninteractive "
                "apt install -y %s" % " ".join(self.cfg["packages"])
            )

    def _validate(self, mode: str) -> Optional[str]:
        if mode == "install":
            res = self.exec("apt -qq list %s" % " ".join(self.cfg["packages"]))
            installed_packages = set()
            for line in res.stdout.decode("utf-8").splitlines():
                installed_package, _ = line.split("/", 1)
                installed_packages.add(installed_package.lower())
            for package in self.cfg["packages"]:
                if package not in installed_packages:
                    return "Apt package %r missing." % package
            return None
        else:
            return None


class Pip3(Whiteprint):

    cfg_schema = {
        # Pin version using '==X.Y.Z' notation.
        "packages": [schema.And(str, schema.Use(str.lower))],
    }

    @staticmethod
    def _mk_package_map(packages: List[str]) -> Dict[str, Optional[str]]:
        """Returns dict mapping package to version."""
        package_map: Dict[str, Optional[str]] = {}
        for package in packages:
            package_name, *version = package.split("==", 1)
            package_map[package_name] = version[0] if version else None
        return package_map

    def _execute(self, mode: str) -> None:
        if mode == "install":
            self.exec("pip3 install %s" % " ".join(self.cfg["packages"]))

    def _validate(self, mode: str) -> Optional[str]:
        package_map = Pip3._mk_package_map(self.cfg["packages"])
        if mode == "install":
            res = self.exec("pip3 show %s" % " ".join(package_map.keys()))
            installed_packages: Dict[str, str] = {}
            for line in res.stdout.decode("utf-8").splitlines():
                # Assumes consistency in presence and order: Version must
                # always exist after Name.
                if line.startswith("Name: "):
                    installed_package = line.split(maxsplit=1)[1]
                elif line.startswith("Version: "):
                    installed_version = line.split(maxsplit=1)[1]
                    installed_packages[installed_package] = installed_version
            for req_package, req_version in package_map.items():
                if req_package not in installed_packages:
                    return "Pip3 package %r missing." % req_package
                elif req_version and req_version != installed_packages[req_package]:
                    return "Pip3 package %r wrong version: %r != %r" % (
                        req_package,
                        req_version,
                        installed_packages[req_package],
                    )
            return None
        else:
            return None


class Folder(Whiteprint):

    cfg_schema = {
        "path": str,
        schema.Optional("owner"): str,
        schema.Optional("group"): str,
        schema.Optional("mode"): int,
        "remove_on_clean": bool,
    }

    default_cfg = {
        "remove_on_clean": True,
    }

    def _execute(self, mode: str) -> None:
        quoted_path = shlex.quote(self.cfg["path"])
        if mode == "install":
            cmd = "mkdir -p "
            if self.cfg.get("mode") is not None:
                cmd += " -m {:o} ".format(self.cfg["mode"])
            cmd += self.cfg["path"]
            self.exec(cmd)
            if self.cfg.get("owner") is not None:
                self.exec("chown {} {}".format(self.cfg["owner"], quoted_path))
            if self.cfg.get("group") is not None:
                self.exec("chgrp {} {}".format(self.cfg["group"], quoted_path))
            if self.cfg.get("mode") is not None:
                self.exec("chmod {:o} {}".format(self.cfg["mode"], quoted_path))
        elif mode == "clean":
            if self.cfg["remove_on_clean"]:
                self.exec("rm -rf {}".format(quoted_path))

    def _validate(self, mode: str) -> Optional[str]:
        quoted_path = shlex.quote(self.cfg["path"])
        if mode == "install":
            res = self.exec(
                'stat -c "%F %U %G %a" {!r}'.format(quoted_path), error_ok=True
            )
            if res.exit_status == 1:
                return "%r does not exist." % quoted_path
            # Use rsplit because %F can return "directory" or a multi-word like
            # "regular empty file"
            file_type, owner, group, file_mode_raw = (
                res.stdout.decode("utf-8").strip().rsplit(maxsplit=3)
            )
            file_mode = int(file_mode_raw, base=8)
            if file_type != "directory":
                return "%r is not a directory." % quoted_path
            elif self.cfg.get("owner") is not None and owner != self.cfg["owner"]:
                return "expected %r to have owner %r, got %r" % (
                    quoted_path,
                    self.cfg["owner"],
                    owner,
                )
            elif self.cfg.get("group") is not None and group != self.cfg["group"]:
                return "expected %r to have group %r, got %r" % (
                    quoted_path,
                    self.cfg["group"],
                    group,
                )
            elif self.cfg.get("mode") is not None and file_mode != self.cfg["mode"]:
                return "expected {!r} to have mode {:o}, got {:o}.".format(
                    quoted_path, self.cfg["mode"], file_mode
                )
            else:
                return None
        elif mode == "clean":
            res = self.exec("stat {!r}".format(quoted_path), error_ok=True)
            if res.exit_status != 1:
                return "expected %r to not exist." % quoted_path
            else:
                return None
        else:
            return None


class FileFromString(Whiteprint):
    """
    Creates a file from a template represented as a string.
    """

    cfg_schema = {
        "contents": str,
        schema.Optional("cfg"): object,
        "dest_path": str,
        schema.Optional("owner"): str,
        schema.Optional("group"): str,
        schema.Optional("mode"): int,
        "remove_on_clean": bool,
    }

    default_cfg = {
        "remove_on_clean": True,
    }

    @classmethod
    def _compute_prefabs_tail(cls, cfg: Config) -> List[Prefab]:
        prefab_cfg = {"path": cfg["dest_path"]}
        if cfg.get("owner"):
            prefab_cfg["owner"] = cfg["owner"]
        if cfg.get("group"):
            prefab_cfg["group"] = cfg["group"]
        if cfg.get("mode"):
            prefab_cfg["mode"] = cfg["mode"]
        return [Prefab(FileExistsValidator, prefab_cfg)]

    def _execute(self, mode: str) -> None:
        quoted_path = shlex.quote(self.cfg["dest_path"])
        if mode in {"install", "update"}:
            self.scp_up_template_from_str(
                self.cfg["contents"],
                self.cfg["dest_path"],
                self.cfg.get("mode", 0o664),
                self.cfg.get("cfg"),
            )
            if self.cfg.get("owner") is not None:
                self.exec("chown {} {}".format(self.cfg["owner"], quoted_path))
            if self.cfg.get("group") is not None:
                self.exec("chgrp {} {}".format(self.cfg["group"], quoted_path))
        elif mode == "clean":
            if self.cfg["remove_on_clean"]:
                self.exec("rm -rf {}".format(quoted_path))

    def _validate(self, mode: str) -> Optional[str]:
        return None


class FileFromPath(Whiteprint):
    """
    Creates a file from a local resource template.
    """

    cfg_schema = {
        "src_path": str,
        schema.Optional("cfg"): object,
        "dest_path": str,
        schema.Optional("owner"): str,
        schema.Optional("group"): str,
        schema.Optional("mode"): int,
        "remove_on_clean": bool,
    }

    default_cfg = {
        "remove_on_clean": True,
    }

    @classmethod
    def _compute_prefabs_tail(cls, cfg: Config) -> List[Prefab]:
        prefab_cfg = {"path": cfg["dest_path"]}
        if cfg.get("owner"):
            prefab_cfg["owner"] = cfg["owner"]
        if cfg.get("group"):
            prefab_cfg["group"] = cfg["group"]
        if cfg.get("mode"):
            prefab_cfg["mode"] = cfg["mode"]
        return [Prefab(FileExistsValidator, prefab_cfg)]

    def _execute(self, mode: str) -> None:
        quoted_path = shlex.quote(self.cfg["dest_path"])
        if mode in {"install", "update"}:
            self.scp_up_template(
                self.cfg["src_path"],
                self.cfg["dest_path"],
                self.cfg.get("mode"),
                self.cfg.get("cfg"),
            )
            if self.cfg.get("owner") is not None:
                self.exec("chown {} {}".format(self.cfg["owner"], quoted_path))
            if self.cfg.get("group") is not None:
                self.exec("chgrp {} {}".format(self.cfg["group"], quoted_path))
        elif mode == "clean":
            if self.cfg["remove_on_clean"]:
                self.exec("rm -rf {}".format(quoted_path))

    def _validate(self, mode: str) -> Optional[str]:
        return None


class Symlink(Whiteprint):
    """
    Creates a symlink.
    """

    cfg_schema = {
        "src_path": str,
        "dest_path": str,
        "remove_on_clean": bool,
    }

    default_cfg = {
        "remove_on_clean": True,
    }

    def _execute(self, mode: str) -> None:
        src_path = shlex.quote(self.cfg["src_path"])
        dest_path = shlex.quote(self.cfg["dest_path"])
        if mode in {"install", "update"}:
            self.exec(f"ln -sf {src_path} {dest_path}")
        elif mode == "clean":
            if self.cfg["remove_on_clean"]:
                self.exec(f"rm -rf {dest_path}")

    def _validate(self, mode: str) -> Optional[str]:
        dest_path = shlex.quote(self.cfg["dest_path"])
        if mode == "install":
            res = self.exec(f'stat -c "%F" {dest_path}', error_ok=True)
            if res.exit_status == 1:
                return f"{dest_path} does not exist."
            file_type = res.stdout.decode("utf-8").strip()
            if file_type != "symbolic link":
                return f"{dest_path} is not a symbolic link."
        return None


class LineInFile(Whiteprint):

    cfg_schema = {
        "path": str,
        "line": schema.And(
            str, lambda line: "\n" not in line, lambda line: "\r" not in line
        ),
    }

    def _execute(self, mode: str) -> None:
        quoted_line = shlex.quote(self.cfg["line"])
        if mode == "install":
            res = self.exec(
                "grep -q {} {}".format(quoted_line, self.cfg["path"]), error_ok=True
            )
            if res.exit_status == 0:
                return None
            elif res.exit_status == 1 or res.exit_status == 2:
                # 1: Line not found in file
                # 2: File does not exist
                self.exec("echo {} >> {}".format(quoted_line, self.cfg["path"]))
            else:
                assert False, "Unknown grep exit status: %d" % res.exit_status
        elif mode == "clean":
            quoted_pattern = shlex.quote("/^{}$/d".format(self.cfg["line"]))
            self.exec(
                'sed --in-place="" {} {}'.format(quoted_pattern, self.cfg["path"])
            )

    def _validate(self, mode: str) -> Optional[str]:
        quoted_line = shlex.quote(self.cfg["line"])
        if mode == "install":
            res = self.exec(
                "grep -q {} {}".format(quoted_line, self.cfg["path"]), error_ok=True
            )
            if res.exit_status == 0:
                return None
            else:
                return "Line {!r}{} not found in {!r}".format(
                    quoted_line[:10],
                    "" if len(quoted_line) < 10 else "...",
                    self.cfg["path"],
                )
        elif mode == "clean":
            res = self.exec(
                "grep -q {} {}".format(quoted_line, self.cfg["path"]), error_ok=True
            )
            if res.exit_status == 1 or res.exit_status == 2:
                return None
            elif res.exit_status == 0:
                return "Found line {!r}{} in {!r}".format(
                    quoted_line[:10],
                    "" if len(quoted_line) < 10 else "...",
                    self.cfg["path"],
                )
            else:
                return "Unknown exit status from grep: {}".format(res.exit_status)
        else:
            return None


class FileExistsValidator(Whiteprint):

    cfg_schema = {
        "path": str,
        schema.Optional("owner"): str,
        schema.Optional("group"): str,
        schema.Optional("mode"): int,
    }

    def _execute(self, mode: str) -> None:
        return None

    def _validate(self, mode: str) -> Optional[str]:
        quoted_path = shlex.quote(self.cfg["path"])
        if mode in "install":
            res = self.exec(
                'stat -c "%F %U %G %a" {!r}'.format(quoted_path), error_ok=True
            )
            if res.exit_status == 1:
                return "%r does not exist." % quoted_path
            # Use rsplit because %F can return "directory" or a multi-word like
            # "regular empty file"
            file_type, owner, group, file_mode_raw = (
                res.stdout.decode("utf-8").strip().rsplit(maxsplit=3)
            )
            file_mode = int(file_mode_raw, base=8)
            if file_type != "regular file":
                return "%r is not a file." % quoted_path
            elif self.cfg.get("owner") is not None and owner != self.cfg["owner"]:
                return "expected %r to have owner %r, got %r" % (
                    quoted_path,
                    self.cfg["owner"],
                    owner,
                )
            elif self.cfg.get("group") is not None and group != self.cfg["group"]:
                return "expected %r to have group %r, got %r" % (
                    quoted_path,
                    self.cfg["group"],
                    group,
                )
            elif self.cfg.get("mode") is not None and file_mode != self.cfg["mode"]:
                return "expected {!r} to have mode {:o}, got {:o}.".format(
                    quoted_path, self.cfg["mode"], file_mode
                )
            else:
                return None
        elif mode == "clean":
            res = self.exec("stat {!r}".format(quoted_path), error_ok=True)
            if res.exit_status != 1:
                return "expected %r to not exist." % quoted_path
            else:
                return None
        else:
            return None
