import copy
from pathlib import Path
import select
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

import jinja2
import schema  # type: ignore

from hussh import Connection  # type: ignore  # pylint: disable=E0611

from .util import dict_deep_update


Config = Dict[str, Any]


class ExecOutput:
    """The output of an executed program."""

    def __init__(self, exit_status: int, stdout: bytes, stderr: bytes):
        self.exit_status = exit_status
        self.stdout = stdout
        self.stderr = stderr

    def __repr__(self) -> str:
        return "ExitStatus({!r}, {!r}, {!r})".format(
            self.exit_status,
            self.stdout[-100:],
            self.stderr[-100:],
        )


T = TypeVar("T")


class WhiteprintError(Exception):
    def log_msg(self) -> str:
        raise NotImplementedError


class RemoteFileNotFoundError(WhiteprintError):
    """
    Raised when downloading a file via SCP fails because it does not exist.
    """

    def __init__(self, msg: str, inner: Exception):  # FIXME
        super().__init__(msg, inner)
        self.msg = msg
        self.inner = inner

    def log_msg(self) -> str:
        return self.msg


class RemoteTargetDirError(WhiteprintError):
    """
    Raised when uploading a file via SCP fails because the target directory
    does not exist.
    """

    def __init__(self, msg: str, inner: Exception):  # FIXME
        super().__init__(msg, inner)
        self.msg = msg
        self.inner = inner

    def log_msg(self) -> str:
        return self.msg


class RemoteExecError(WhiteprintError):
    """
    Raised when the remote exec returned a non-zero exit status.
    """

    def __init__(self, cmd: str, exec_output: ExecOutput):
        super().__init__(cmd, exec_output)
        self.cmd = cmd
        self.exec_output = exec_output

    def log_msg(self) -> str:
        stdout = self.exec_output.stdout.decode("utf-8", "ignore")
        stderr = self.exec_output.stderr.decode("utf-8", "ignore")
        return (
            "Remote Exec Failed: {}\n" "exit status: {}\n" "stdout: {}\n" "stderr: {}\n"
        ).format(
            self.cmd,
            self.exec_output.exit_status,
            stdout,
            stderr,
        )


class ValidationError(WhiteprintError):
    """Raised when whiteprint validation fails."""

    def __init__(self, msg: str):
        super().__init__(msg)
        self.msg = msg

    def log_msg(self) -> str:
        return self.msg


_target_host_cfg_schema = {
    schema.Optional("_target"): {
        "user": str,
        "host": str,
        "kernel": str,
        "distro": str,
        "distro_version": str,
        "hostname": str,
        "fqdn": str,
        "cpu_count": int,
    }
}


class Whiteprint:
    """
    Subclass and implement the execute() method.

    The purpose of the whiteprint is to encapsulate the logic for various
    operation modes on a target host (install, update, clean, start, stop,
    ...). The logic will tend to be a mixture of shell commands run remotely,
    and file creation/modification with template variable substitution.

    Whiteprints do not manage the opening and closing of session objects.
    """

    # The name is used to look up the folder containing rsrcs for this
    # whiteprint by the siteplan.
    name: Optional[str] = None

    default_cfg: Config = {}

    cfg_schema: Optional[Config] = None

    prefabs_head: List["Prefab"] = []

    prefabs_tail: List["Prefab"] = []

    def __init__(
        self,
        conn: Connection,
        site_cfg: Optional[Config] = None,
        rsrc_path: Optional[Path] = None,
    ) -> None:
        """
        Args:
             conn: Responsibility of caller to close this.
             rsrc_path: Path to the location where relative-path specified
                resources can be found.
        """
        self.conn = conn
        self.cfg: Config = copy.deepcopy(self.default_cfg)
        if site_cfg is not None:
            self.cfg.update(site_cfg)
        self.rsrc_path = rsrc_path
        assert self.rsrc_path is None or self.rsrc_path.exists()

        if self.cfg_schema:
            self.cfg = schema.Schema(
                {**self.cfg_schema, **_target_host_cfg_schema}
            ).validate(self.cfg)

        computed_prefabs_head = self._compute_prefabs_head(self.cfg)
        if computed_prefabs_head:
            self.prefabs_head = self.prefabs_head[:] + computed_prefabs_head
        computed_prefabs_tail = self._compute_prefabs_tail(self.cfg)
        if computed_prefabs_tail:
            self.prefabs_tail = self.prefabs_tail[:] + computed_prefabs_tail

    @classmethod
    def _compute_prefabs_head(
        cls, cfg: Config  # pylint: disable=W0613
    ) -> List["Prefab"]:
        return []

    @classmethod
    def _compute_prefabs_tail(
        cls, cfg: Config  # pylint: disable=W0613
    ) -> List["Prefab"]:
        return []

    def exec(
        self, cmd: str, error_ok: bool = False
    ) -> ExecOutput:
        """
        Executes cmd in a session channel.

        Args:
            cmd: Executed in the context of a shell.
            error_ok: If true, does not raise a RemoteExecError if exist status
                is non-zero.
        """
        exec_res = self.conn.execute(cmd)

        exec_output = ExecOutput(exec_res.status, exec_res.stdout, exec_res.stderr)
        if exec_output.exit_status != 0 and not error_ok:
            raise RemoteExecError(cmd, exec_output)
        else:
            return exec_output

    def _resolve_rsrc(self, raw_path: str) -> Path:
        raw_path_obj = Path(raw_path)
        if raw_path_obj.is_absolute():
            return raw_path_obj
        else:
            assert self.rsrc_path is not None, (
                "Need rsrc_path for lookup of %r but none set." % raw_path
            )
            resolved_path = self.rsrc_path / raw_path_obj
            assert resolved_path.exists(), "Could not find rsrc %r" % raw_path
            return resolved_path

    def _scp_send64_helper(
        self, dest_path: str, mode: int, size: int, mtime: int, atime: int
    ) -> Channel:
        try:
            return retry_eagain(
                self.session.scp_send64, dest_path, mode & 0o777, size, mtime, atime
            )
        except SCPProtocolError as e:
            # Unfortunately, very coarse error without any more info. It very
            # possibly occurs in other circumstances as well.
            assert e.args == ()
            raise RemoteTargetDirError("%r is a bad path." % dest_path, e) from e

    def _scp_recv2_helper(self, src_path: str) -> Tuple[Channel, FileInfo]:
        try:
            # Hack for mypy
            scp_recv2: Callable[..., Tuple[Channel, FileInfo]] = self.session.scp_recv2
            return retry_eagain(scp_recv2, src_path)
        except SCPProtocolError as e:
            # Unfortunately, very coarse error without any more info. It very
            # possibly occurs in other circumstances as well.
            assert e.args == ()
            raise RemoteFileNotFoundError("%r not found." % src_path, e) from e

    def scp_up(self, src_path: str, dest_path: str, mode: Optional[int] = None) -> None:
        """
        Args:
            src_path: A path on the local filesystem.
            dest_path: A path on the remote filesystem.
            mode: The ACL for the new destination file. If omitted, uses the
                ACL on the source file.
        """
        src_path_obj = self._resolve_rsrc(src_path)
        fileinfo = src_path_obj.stat()
        if mode is None:
            mode = fileinfo.st_mode
        chan = self._scp_send64_helper(
            dest_path,
            mode,
            fileinfo.st_size,
            int(fileinfo.st_mtime),
            int(fileinfo.st_atime),
        )
        with src_path_obj.open("rb") as f:
            for data in f:
                mv_data = memoryview(data)
                while True:
                    _, sent = chan.write(bytes(mv_data))
                    mv_data = mv_data[sent:]
                    if len(mv_data) == 0:
                        break
        while chan.send_eof() == LIBSSH2_ERROR_EAGAIN:
            continue
        while chan.wait_eof() == LIBSSH2_ERROR_EAGAIN:
            continue
        while chan.wait_closed() == LIBSSH2_ERROR_EAGAIN:
            continue
        chan.close()

    def scp_down(self, src_path: str, dest_path: str) -> None:
        """
        Args:
            src_path: A path on the remote filesystem.
            dest_path: A path on the local filesystem.
        """
        chan, fileinfo = self._scp_recv2_helper(src_path)
        expected_size = fileinfo.st_size
        with open(dest_path, "wb") as f:
            while True:
                size, data = chan.read()
                while size == LIBSSH2_ERROR_EAGAIN:
                    size, data = chan.read()
                if size == expected_size + 1:
                    f.write(data[:-1])
                    retry_eagain(chan.close)
                    return
                else:
                    f.write(data)
                    expected_size -= size

    def scp_up_from_bytes(self, data: bytes, dest_path: str, mode: int = 0o664) -> None:
        """
        Create a new file at the destination from bytes in memory.

        Args:
            data: The contents for the new destination file.
            dest_path: A path on the remote filesystem.
            mode: The ACL for the new destination file. If omitted, uses the
                ACL on the source file.
        """
        assert isinstance(data, bytes)

        def chunks(l: bytes, n: int) -> Iterable[bytes]:
            n = max(1, n)
            return (l[i : i + n] for i in range(0, len(l), n))

        # Goal: mtime/atime to be set to the current time on the target
        # machine. Solution: Setting mtime/atime to 0 seems to work.
        chan = self._scp_send64_helper(dest_path, mode, len(data), 0, 0)
        # TODO: Find optimal chunk size.
        for chunk in chunks(data, 32_000):
            mv_chunk = memoryview(chunk)
            while True:
                _, sent = chan.write(bytes(mv_chunk))
                mv_chunk = mv_chunk[sent:]
                if len(mv_chunk) == 0:
                    break
        while chan.send_eof() == LIBSSH2_ERROR_EAGAIN:
            continue
        while chan.wait_eof() == LIBSSH2_ERROR_EAGAIN:
            continue
        while chan.wait_closed() == LIBSSH2_ERROR_EAGAIN:
            continue
        chan.close()

    def scp_down_to_bytes(self, src_path: str) -> bytes:
        """
        Download a file from the destination to memory.

        Args:
            src_path: A path on the remote filesystem.

        Returns:
            Contents of the requested file.
        """
        chan, fileinfo = self._scp_recv2_helper(src_path)
        expected_size = fileinfo.st_size

        data = b""
        while True:
            size, chunk = chan.read()
            while size == LIBSSH2_ERROR_EAGAIN:
                size, chunk = chan.read()
            if size == expected_size + 1:
                data += chunk[:-1]
                retry_eagain(chan.close)
                return data
            else:
                data += chunk
                expected_size -= size

    def _resolve_cfg(self, cfg_override: Optional[Config]) -> Config:
        if cfg_override is not None:
            cfg = copy.deepcopy(self.cfg)
            dict_deep_update(cfg, cfg_override)
        else:
            cfg = self.cfg
        return cfg

    def scp_up_template(
        self,
        src_path: str,
        dest_path: str,
        mode: Optional[int] = None,
        cfg_override: Optional[Config] = None,
    ) -> None:
        """
        Args:
            src_path: Path to a jinja template file. Variable substitution will
                be done before upload.
            cfg_override: Additional configuration variables with precedence
                over those of this whiteprint.
        See :meth:`src_up`.
        """
        cfg = self._resolve_cfg(cfg_override)
        src_path_obj = self._resolve_rsrc(src_path)
        if mode is None:
            fileinfo = src_path_obj.stat()
            mode = fileinfo.st_mode

        with src_path_obj.open(encoding="utf8") as f:
            template_contents = f.read()
        template = jinja2.Template(template_contents, undefined=MostlyStrictUndefined)
        rendered_template = template.render(cfg).encode("utf-8")
        self.scp_up_from_bytes(rendered_template, dest_path, mode)

    def scp_up_template_from_str(
        self,
        template_contents: str,
        dest_path: str,
        mode: int = 0o664,
        cfg_override: Optional[Config] = None,
    ) -> None:
        cfg = self._resolve_cfg(cfg_override)
        template = jinja2.Template(template_contents, undefined=MostlyStrictUndefined)
        rendered_template = template.render(cfg).encode("utf-8")
        self.scp_up_from_bytes(rendered_template, dest_path, mode)

    @staticmethod
    def render_template(template_contents: str, cfg: Config) -> str:
        template = jinja2.Template(template_contents, undefined=MostlyStrictUndefined)
        return template.render(cfg)

    def execute(self, mode: str) -> None:
        for prefab in self.prefabs_head:
            try:
                self.use_execute(mode, prefab.whiteprint_cls, prefab.cfg)
            except NotImplementedError:
                pass
        try:
            self._execute(mode)
        except NotImplementedError:
            pass
        for prefab in self.prefabs_tail:
            try:
                self.use_execute(mode, prefab.whiteprint_cls, prefab.cfg)
            except NotImplementedError:
                pass

    def _execute(self, mode: str) -> None:
        """
        To be implemented by inheriting class.

        Execute receives a mode (install, update, clean ...) and is expected
        to run the appropriate deployment commands.
        """
        raise NotImplementedError

    def validate(self, mode: str) -> Optional[str]:
        for prefab in self.prefabs_head:
            try:
                self.use_validate(mode, prefab.whiteprint_cls, prefab.cfg)
            except NotImplementedError:
                continue
        try:
            err = self._validate(mode)
        except NotImplementedError:
            pass
        else:
            if err:
                return err
        for prefab in self.prefabs_tail:
            try:
                self.use_validate(mode, prefab.whiteprint_cls, prefab.cfg)
            except NotImplementedError:
                continue
        return None

    def _validate(self, mode: str) -> Optional[str]:
        raise NotImplementedError

    def use_execute(
        self,
        mode: str,
        whiteprint_cls: Type["Whiteprint"],
        cfg: Optional[Config] = None,
    ) -> None:
        """
        Execute another whiteprint from this whiteprint.
        """
        wp = whiteprint_cls(self.session, cfg, self.rsrc_path)
        wp.execute(mode)

    def use_validate(
        self,
        mode: str,
        whiteprint_cls: Type["Whiteprint"],
        cfg: Optional[Config] = None,
    ) -> None:
        """
        Run validation of another whiteprint from this whiteprint.

        Raises:
            - ValidationError: If validation failed.
        """
        wp = whiteprint_cls(self.session, cfg, self.rsrc_path)
        err = wp.validate(mode)
        if err:
            raise ValidationError(err)


class MostlyStrictUndefined(jinja2.Undefined):
    """Just like jinja2's built-in except __bool__ is allowed.

    This allows templates to check whether a variable is defined (also
    conflated with truthy) without raising an error. However, all other uses
    of an undefined will raise an error.
    """

    __slots__ = ()
    # Alright black... whatever you say.
    __iter__ = (
        __str__
    ) = (
        __len__
    ) = (
        __nonzero__
    ) = (
        __eq__
    ) = (
        __ne__
    ) = (
        __hash__
    ) = jinja2.Undefined._fail_with_undefined_error  # pylint:disable=protected-access


class Prefab:
    """
    Intended to provide declarative deployment specifications.

    Requirements:
    - A whiteprint that implements execute & validate for default modes:
        install, update, start, stop
    - A whiteprint that's idempotent: can be reliably retried on failure.
    """

    def __init__(self, whiteprint_cls: Type[Whiteprint], cfg: Optional[Config] = None):
        self.whiteprint_cls = whiteprint_cls
        self.cfg = cfg
