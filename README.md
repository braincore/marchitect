# Marchitect [![Latest Version]][PyPI]

[Latest Version]: https://img.shields.io/pypi/v/marchitect.svg
[PyPI]: https://pypi.org/project/marchitect/

A tool for uploading files to and running commands on remote hosts.

## Install

```bash
$ pip3 install marchitect
```

## Example

Let's write a couple of files to your machine assuming that it could easily be
made to be a remote machine.

```python
from marchitect.site_plan import SitePlan, Step
from marchitect.whiteprint import Whiteprint

class HelloWorldWhiteprint(Whiteprint):

    name = 'hello_world'  

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            # Write file by running remote shell commands.
            self.exec('echo "hello, world." > /tmp/helloworld1')
            # Write file by uploading
            self.scp_up_from_bytes(
                b'hello, world.', '/tmp/helloworld2')

class MyMachine(SitePlan):
    plan = [
        Step(HelloWorldWhiteprint)
    ]
    
if __name__ == '__main__':
    # SSH into your own machine, prompting you for your password.
    import getpass
    import os
    user = os.getlogin()
    password = getpass.getpass('%s@localhost password: ' % user)
    sp = MyMachine.from_password('localhost', 22, user, password, {}, [])
    # If you want to auth by private key, use the below:
    # (Note: The password prompt will be for your private key, empty for none.)
    #sp = MyMachine.from_private_key(
    #    'localhost', 22, user, '/home/%s/.ssh/id_rsa' % user, password, {}, [])
    sp.install()  # Sets the mode of _execute() to install.
```

This example requires that you can SSH into your machine via password. To use
your SSH key instead, uncomment the lines above. After execution, you should
have `/tmp/helloworld1` and `/tmp/helloworld2` on your machine.

Hopefully it's clear that whiteprints let you run commands and upload files to a
target machine. A whiteprint should contain all the operations for a common
purpose. A site plan contains all the whiteprints that should be run on a
single machine class.

Steps for deploying your code repository to a machine would make for a good
whiteprint. A site plan for a machine that runs your web servers might use that
whiteprint and others.

## Goals

* Easy to get started.
* Templating of configuration files.
* Mix of imperative and declarative styles.
* Arbitrary execution modes (install, update, clean, start, stop, ...).
* Interface for validating machine state.
* Be lightweight because most complex configurations are happening in
  containers anyway.

## Non-goals

* Making whiteprints and site plans share-able with other people and companies.
* Non-Linux deployment targets.

## Concepts

### Whiteprint

To create a whiteprint, extend `Whiteprint` and define a `name` class variable
and an `_execute()` method; optionally define a `validate()` method. `name`
should be a reasonable name for the whiteprint. In the example above, the
`HelloWorldWhiteprint` class's name is simply `hello_world`. `name` is
important for file resolution which is discussed below.

`_execute()` is where all the magic happens. The method takes a string called
`mode`. Out of convention, your whiteprints should handle the following modes:

* `install` (installing software)
* `update` (updating software)
* `clean` (removing software, if needed, but generally impractical)
* `start` (starting services)
* `stop` (stopping services).

Despite this convention, `mode` can be anything as you'll be choosing the modes
to execute your site plans with.

Within `_execute()`, you're given all the freedom to shoot yourself in the
foot. Use `self.exec()` to run any command on the target machine.

`exec()` returns an `ExecOutput` object with variables `exit_status` (int),
`stdout` (bytes), and `stderr` (bytes). You can use these outputs to control
flow. If the exit status is non-zero, a `RemoteExecError` is raised. To
suppress the exception, set `error_ok=True`.

`_execute()` has access to `self.cfg` which are the config variables for the
whiteprint. See the Templates & Config Vars section below.

Use the variety of functions to copy files to and from the host:

* `scp_up()` - Upload a file from the local host to the target.
* `sp_up_from_bytes()` - Create a file on the target host from the bytes arg.
* `scp_down()` - Download a file from the target to the local host.
* `scp_down_to_bytes()` - Download a file from the target and return it.

#### Templates & Config Vars

You can upload files that are [jinja2](http://jinja.pocoo.org) templates. The
templates will be filled by the config variables passed to the whiteprint.
Config variables can be set in a few ways, which we'll explore.

Here's a sample `test.toml` file that uses the jinja2 notation to specify a
`name` variable with a default of `John Doe`:

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
            # 'Bob' overrides 'Alice'
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
    MyMachine.from_password(..., cfg={WhiteprintExample: {'name': 'Foo'}})
```

In the above, `Foo` takes precedence over `Eve` which takes precedence over any
values for `name` defined in the whiteprint.

##### Config Override by Alias

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
    MyMachine.from_password(..., cfg={'ex1': 'Eve', 'ex2': 'Foo'})
```

In the above, the first `WhiteprintExample` uploads `Eve` and the second
replaces it with `Foo`.

##### Auto-Derived Configs

Auto-derived config variables are always available without specification.
These are stored in `self.cfg['_target']`:

* `user`: The login user for the SSH connection.
* `host`: The target host for the SSH connection.
* `kernel`: The kernel version of the target host. Ex: `4.15.0-43-generic`
* `distro`: The Linux distribution of the target host. Ex: `ubuntu`
* `disto_version`: The version of the Linux distribution. Ex: `18.04`
* `hostname`: The hostname of the target host.
* `fqdn`: The fully-qualified domain name of the target host.
* `cpu_count`: The number of CPUs on the target host. Ex: `8`


#### Config Var Schema

Because config vars may be used in external template files, it's not readily
observable what vars are used by a whiteprint. To make config vars explicit,
a schema can be set using `cfg_schema`:

```python
from marchitect.whiteprint import Whiteprint
import schema

class WhiteprintExample(Whiteprint):

    cfg_schema = {
        'name': str,
        schema.Optional('path'): str,
        'targets': [str],
    }
    ...
```

The schema is enforced on execution of the whiteprint.

For more info on expressing schemas (nesting, lists, optionals), see
[schema](https://pypi.org/project/schema/).

#### File Resolution

Methods that upload local files (`scp_up()` and `scp_up_template()`) will
search for the files according to the `rsrc_paths` argument in the `SitePlan`
constructor. The search proceeds in order of the `rsrc_paths` and the name of
the whiteprint is expected to be the name of a subfolder in the `rsrc_path`.

For example, assume `rsrc_paths` is `[Path('/srv/rsrcs')]`, the whiteprint
has a name of `foobar`, and the file `c` is referenced as `a/b/c`. The resolver
will look for the existence of `/srv/rsrcs/foobar/a/b/c`.

If a file path is specified as absolute, say `/a/b/c`, no `rsrc_path` will be
prefixed. However, this form is not encouraged for portability across machines
as resources may live in different folders on different machines.

#### Idempotence

It's important to strive for the idempotence of your whiteprints. In other
words, assume your whiteprint in any mode (install, update, ...) can be
interrupted at any point. Can your whiteprint be re-applied successfully
without any problems?

If so, your whiteprint is idempotent and is therefore resilient to connection
errors and software hiccups. Error handling will be as easy as retrying your
whiteprint a bounded number of times. If not, you'll need to figure out an
error handling strategy. In the extreme case, you can terminate servers that
produce errors and start over with a fresh one, assuming that you're in a cloud
environment.

#### Prefab

Prefabs are built-in, robust whiteprints you can use in your whiteprints.
These make it easy to add common functionality with the `_execute()` and
`_validate()` methods already defined. These are available out-of-the-box:

* `Apt`: Common Linux package manager.
* `Pip3`: Python package manager.
* `Folder`: Makes a folder exists at the specified path.
* `LineInFile`: Ensures the specified line exists in the specified file.
* `FileFromString`: Makes a file at a specified path.
* `FileFromPath`: Makes a file at a specified path.
* `Symlink`: Makes a symlink.
* `FileExistsValidator`: Only validates that a file exists at a specified path.

An example:

```python
from marchitect.prefab import Apt
from marchitect.whiteprint import Prefab, Whiteprint

class HelloWorld2Whiteprint(Whiteprint):

    prefabs_head = [
        Prefab(Apt, {'packages': ['curl']}),
    ]

    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.exec('curl https://www.nytimes.com > /tmp/nytimes')
```

`prefabs_head` are applied before your `_execute()` and `_validate()` methods,
respectively. Alternatively, `prefabs_tail` are applied after.

If a prefab depends on a config variable, define a `_compute_prefabs_head()`
class method:

```python
from typing import Any, Dict, List
from marchitect.prefab import Folder
from marchitect.whiteprint import Prefab, Whiteprint

class ExampleWhiteprint(Whiteprint):

    cfg_schema = {
        'temp_folder': str,
    }

    @classmethod
    def _compute_prefabs_head(cls, cfg: Dict[str, Any]) -> List[Prefab]:
        return [Prefab(Folder, {'path': cfg['temp_folder']})]
```

The prefabs returned by`_compute_prefabs_head()` will be applied after those
specified directly in the `prefabs_head` class variable.

#### Nested Whiteprints

Whiteprints can use other whiteprints.

```python
from marchitect.whiteprint import Whiteprint

class Example2Whiteprint(Whiteprint):
    pass

class ExampleWhiteprint(Whiteprint):
    def _execute(self, mode: str) -> None:
        if mode == 'install':
            self.use_execute(mode, Example2Whiteprint, {})

    def _validate(self, mode: str) -> None:
        if mode == 'install':
            self.use_validate(mode, Example2Whiteprint, {})
```

### Site Plan

Site plans are collections of whiteprints. You likely have distinct roles for
the machines in your infrastructure: web hosts, api hosts, database hosts, ...
Each of these should map to their own site plan which will install the
appropriate whiteprints (postgres for database hosts, uwsgi for web hosts, ...).

## Testing

Tests are run against real SSH connections, which unfortunately makes it
difficult to run in a CI environment. Travis CI is not enabled for this reason.
When running tests through `py.test` or `tox`, you can specify SSH credentials
either as a user/pass pair or user/private_key. For example:

```
SSH_USER=username SSH_HOST=localhost SSH_PRIVATE_KEY=~/.ssh/id_rsa SSH_PRIVATE_KEY_PASSWORD=*** py.test
SSH_USER=username SSH_HOST=localhost SSH_PASSWORD=*** py.test -sx
```

Will likely move to mocking SSH commands, but it will be painful to reliably
mock the interfaces for `ssh2-python`.

`mypy` and `lint` are also supported: `tox -e mypy,lint`

## TODO
* [ ] Add "common" dependencies to minimize invocations of commands like
  `apt update` to once per site plan.
* [ ] Write a log of applied site plans and whiteprints to the target host
  for easy debugging.
* [ ] Add documentation for `validate()` method.
* [ ] Verify speed wins by using `ssh2-python` instead of `paramiko`.
* [ ] Document `SitePlan.one_off_exec()`.
* [ ] File prefabs can use md5sum to decide whether to re-create file.
