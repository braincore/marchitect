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
    #sp = MyMachine.from_private_key(
    #    'localhost', 22, user, '/home/%s/.ssh/id_rsa' % user, password, {}, [])
    sp.install()  # Sets the mode of _execute() to install.
