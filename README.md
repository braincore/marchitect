# Marchitect

A tool for uploading files to and running commands on remote hosts.

## Install

```bash
$ pip3 install marchitect
```

## Example

Let's install `httpie` on your machine and do a couple more things.

```python
from marchitect.site_plan import Step, SitePlan
from marchitect.whiteprint import Whiteprint

class HttpieWhiteprint(Whiteprint):

    name = 'httpie'  # See `file resolution`

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.exec('pip3 install --user httpie')
            self.exec('.local/bin/http https://www.nytimes.com > /tmp/nytimes')
            self.scp_up_from_bytes(
                b'hello, world', '/tmp/helloworld')

class MyMachine(SitePlan):
    plan = [
        Step(HttpieWhiteprint)
    ]
    
if __name__ == '__main__':
    import getpass
    import os
    user = os.getlogin()
    password = getpass.getpass('%s@localhost password: ' % user)
    sp = MyMachine.from_password('localhost', 22, user, password, {}, [])
    #sp = MyMachine.from_private_key(
    #    'localhost', 22, user, '/home/%s/.ssh/id_rsa' % user, password, {}, [])
    sp.install()
```

This example requires that you can SSH into your machine via password. To use
your SSH key instead, uncomment the lines above. After execution, you should
have `/tmp/nytimes` and `/tmp/helloworld` on your machine.

Hopefully it's clear that whiteprints let you run commands and upload files to a
target machine. A whiteprint should contain all the operations for a common
purpose. A siteplan contains all the whiteprints that should be run on a single
machine class.

## Goals

* Easy to get started.
* Templating of configuration files.
* Mix of imperative and declarative styles.
* Arbitrary execution modes (install, update, clean, start, stop, ...).
* Interface for validating machine state.
* Be lightweight because most complex configurations are happening in containers anyway.

## Non-goals

* Making whiteprints and siteplans share-able with other people and companies.
* Non-Linux deployment targets.

## Concepts

### Whiteprint

To create a whiteprint, extend `Whiteprint` and define a `name` class variable
and an `_execute()` method; optionally define a `validate()` method. `name`
should be a reasonable name for the whiteprint. In the example above, the
`HttpieWhiteprint` class's name is simply `httpie`. `name` is important for
file resolution which is discussed below.

`_execute()` is where all the magic happens. The method takes a string called
`mode`. Out of convention, your whiteprints should handle the following modes:
`install` (installing software), `update` (updating software), `clean`
(removing software, if needed), `start` (starting services), and `stop`
(stopping services).

Despite this convention, `mode` can be anything as you'll be executing your
site plan with a `mode` you specify, which will propagate to your whiteprints.

Within `_execute()`, you're given all the freedom to shoot yourself in the
foot. Use `self.exec()` to run any command.

`exec()` returns an `ExecOutput` object with variables `exit_status` (int),
`stdout` (bytes), and `stderr` (bytes). You can use these outputs to control
flow. If the exit status is non-zero, a `RemoteExecError` is raised. To
suppress the exception, set `error_ok=True`.

`exec()` has access to `self.cfg` which are the config variables for the
whiteprint. See the Templates & Config Vars section below.

Use the variety of upload functions to copy files onto the host:

* `scp_up()` - Upload a file from the local host to the target.
* `sp_up_from_bytes()` - Create a file on the target host from the bytes arg.
* `scp_down()` - Download a file from the target to the local host.
* `scp_down_to_bytes()` - Download a file from the target and return it.

#### Templates & Config Vars

You can upload files that are [jinja2](http://jinja.pocoo.org) templates. The
templates will be filled by the config variables passed to the whiteprint.
Config variables can be set in numerous ways, which we'll now explore.

Here's a sample `test.toml` file that uses the jinja2 notation to specify a
name variable with a default of `John Doe`:

```toml
name = "{{ name|default('John Doe') }}"
```

A whiteprint can populate a template for upload as follows:

```python
from marchitect.whiteprint import Whiteprint

class WhiteprintExample(Whiteprint):

    default_cfg = {'name': 'Alice'}

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.scp_up_template('/path/to/test.toml', '~/test.toml')
```

A whiteprint can also upload a populated template that's stored in a string
rather than a file:

```python
from marchitect.whiteprint import Whiteprint

class WhiteprintExample(Whiteprint):

    default_cfg = {'name': 'Alice'}

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.scp_up_template_from_str(
                'name = "{{ name }}"', '~/test.toml')
```

A config var can be overriden in `scp_up_template_from_str`:

```python
from marchitect.whiteprint import Whiteprint

class WhiteprintExample(Whiteprint):

    default_cfg = {'name': 'Alice'}

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.scp_up_template_from_str(
                'name = "{{ name }}"', '~/test.toml',
                cfg_override={'name': 'Bob'})
```

Config vars can also be set by the `SitePlan` in the plan or during
instantiation.

```python
from marchitect.site_plan import Step, SitePlan

class MyMachine(SitePlan):
    plan = [
        Step(WhiteprintExample, {'name': 'Eve'})
    ]

if __name__ == '__main__':
    MyMachine.from_password(..., cfg_override={'name': 'Foo'})
```

In the above, `Foo` takes precedence over `Eve`.

Finally, a `Step` can be given an alias as another identifier for specifying
config vars. This is useful when a whiteprint is used multiple times in a site
plan.

```python
from marchitect.site_plan import Step, SitePlan

class MyMachine(SitePlan):
    plan = [
        Step(WhiteprintExample, alias="ex1"),
        Step(WhiteprintExample, alias="ex2"),
    ]

if __name__ == '__main__':
    MyMachine.from_password(..., cfg_override={'ex1': 'Eve', 'ex2': 'Foo'})
```

In the above, the first `WhiteprintExample` uploads `Eve` and the second
replaces it with `Foo`.

There are also config variables that are auto-derived and always available.
These are stored in `self.cfg['_target']`:

* `user`: The login user for the SSH connection.
* `host`: The target host for the SSH connection.
* `kernel`: The kernel version of the target host. Ex: `4.15.0-43-generic`
* `distro`: The Linux distribution of the target host. Ex: `ubuntu`
* `disto_version`: The version of the Linux distribution. Ex: `18.04`
* `hostname`: The hostname of the target host.
* `fqdn`: The fully-qualified domain name of the target host.
* `cpu_count`: The number of CPUs on the target host. Ex: `8`


#### File Resolution

Methods that upload local files (`scp_up()` and `scp_up_template()`) will
search for the files according to the `rsrc_paths` argument in the `SitePlan`
constructor. The search proceeds in order of the `rsrc_paths` and the name of
the whiteprint is expected to be the name of a subfolder in the `rsrc_path`.

For example, assume `rsrc_paths` is `[Path('/srv/rsrcs')]`, the whiteprint
has a name of `foobar`, and the file `c` is referenced as `a/b/c`. The resolver
will look for the existence of `/srv/rsrcs/foobar/a/b/c`.

If a file path is specified as absolute, say `/a/b/c`, no `rsrc_path` will be
prefixed. However, this form is not encouraged as resources will live in
different folders on different machines

#### Idempotence

The most important consideration for your whiteprints is to strive for
idempotence. In other words, assume your whiteprint in any mode (install,
update, ...) can be interrupted at any point. Can your whiteprint be re-applied
successfully without any problems?

If so, your whiteprint is idempotent and is
therefore resilient to connection errors and software hiccups. Error handling
will be as easy as retrying your whiteprint a bounded number of times. If not,
you'll need to figure out an error handling strategy. In the extreme case, you
can terminate servers that produce errors and start over with a fresh one,
assuming that you're in a cloud environment.

### Prefab

Prefabs are built-in idempotent components you can add to your whiteprints.
These make it easy to add common functionality with the execution and
validation already defined. Currently, `Apt`, `Pip3`, `FolderExists`, and
`LineInFile` are available.

Rewriting the first example:

```python
from marchitect.prefab import Pip3
from marchitect.whiteprint import Whiteprint

class HttpieWhiteprint(Whiteprint):

    prefabs = [
        Pip3(['httpie']),
    ]

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.exec('.local/bin/http https://www.nytimes.com > /tmp/nytimes')
            self.scp_up_from_bytes(
                b'hello, world', '/tmp/helloworld')
```

Prefabs are executed before your overloaded `_execute()` method.

If a prefab depends on a config variable, define a `_compute_prefabs()` class
method:

```python
from typing import Any, Dict, List
from marchitect.prefab import FolderExists, Prefab
from marchitect.whiteprint import Whiteprint

class ExampleWhiteprint(Whiteprint):

    @classmethod
    def _compute_prefabs(cls, cfg: Dict[str, Any]) -> List[Prefab]:
        return [FolderExists(cfg['temp_folder'])]
```

The prefabs returned by`_compute_prefabs()` will be executed after those
specified in the `prefabs` class variable.

### Site Plan

Site plans are collections of whiteprints. You likely have distinct roles for
the machines in your infrastructure: web hosts, api hosts, database hosts, ...
Each of these should map to their own site plan which will install the
appropriate whiteprints (postgres for database hosts, uwsgi for web hosts, ...).

## Testing

Tests are run against real SSH connections, which unfortunately makes it
difficult to run in a CI environment. You can specify SSH credentials either
as a user/pass pair or user/private_key. For example:

```
SSH_USER=username SSH_HOST=localhost SSH_PRIVATE_KEY=~/.ssh/id_rsa SSH_PRIVATE_KEY_PASSWORD=*** py.test
SSH_USER=username SSH_HOST=localhost SSH_PASSWORD=*** py.test -sx
```

Will likely move to mocking SSH commands, but it will be painful to reliably
mock the interfaces for `ssh2-python`.

## TODO
* [] Add "common" dependencies to minimize invocations of commands like
  `apt update` to once per site plan.
* [] Write a log of applied site plans and whiteprints to the target host
  for easy debugging.
* [] Add documentation for `validate()` method.
* [] Verify speed wins by using `ssh2-python` instead of `paramiko`.
* [] Document `SitePlan.one_off_exec()`.
