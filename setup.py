#!/usr/bin/env python3

from setuptools import setup

setup(
    name='envlinkfs',
    version_format='{tag}.dev{commitcount}+{gitsha}',
    description='FUSE filesystem that exposes environment variables as symbolic links',
    url='https://github.com/Akaricchi/envlinkfs',
    author='Andrey Alexeyev',
    author_email='akari@alienslab.net',
    license='WTFPL',
    py_modules=['envlinkfs'],
    install_requires=['fusepy'],
    setup_requires=['setuptools-git-version'],
    zip_safe=True,
    entry_points = {
        'console_scripts': ['envlinkfs=envlinkfs:main'],
    }
)
