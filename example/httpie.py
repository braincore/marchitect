from marchitect.site_plan import SitePlan
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
        (HttpieWhiteprint, {})
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
