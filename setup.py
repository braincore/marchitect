from setuptools import setup

setup(
    name='marchitect',
    version='0.1',
    description='Machine architect for software deployment.',
    author='Ken Elkabany',
    author_email='ken@elkabany.com',
    license='MIT',
    url='https://www.github.com/kelkabany/marchitect',
    packages=['marchitect'],
    install_requires=[
        'jinja2>=2.10',
        'ssh2-python>=0.17.0'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
)
