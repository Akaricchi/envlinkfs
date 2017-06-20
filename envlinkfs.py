#!/usr/bin/env python3

import os
import errno
import stat
import contextlib

from fuse import (
    FUSE,
    FuseOSError,
    Operations,
    fuse_get_context,
)


proc_env_cache = {}
proc_env_cache_times = {}


def remap_pid(pid):
    with open('/proc/%d/status' % pid) as sfile:
        status = dict(i.split(':\t') for i in filter(None, sfile.read().split('\n')))

    try:
        if (status['voluntary_ctxt_switches']    == '1' and
            status['nonvoluntary_ctxt_switches'] in ('0', '1')):

            # looks like the process just forked from another one
            # reading from its environ at this point will block forever

            # try to use the parent process instead
            # far from ideal, but should work in most cases...

            return int(status['PPid'])
    except KeyError:
        pass

    return pid


def read_proc_env(path):
    try:
        with open(path, 'rb') as env:
            return dict((s.decode('utf8').split('=', 1) for s in filter(None, env.read().split(b'\x00'))))
    except OSError:
        return {}


def cache_proc_env(pid, path, mtime):
    e = read_proc_env(path)
    proc_env_cache[pid] = e
    proc_env_cache_times[pid] = mtime
    return e


def get_proc_env(pid):
    # XXX: Linux-like procfs on /proc required

    pid = remap_pid(pid)
    epath = '/proc/%d/environ' % pid

    try:
        estat = os.lstat(epath)
    except OSError:
        with contextlib.suppress(KeyError):
            del proc_env_cache[pid]

        with contextlib.suppress(KeyError):
            del proc_env_cache_times[pid]

        return {}

    try:
        cached_mtime = proc_env_cache_times[pid]
    except KeyError:
        return cache_proc_env(pid, epath, estat.st_mtime)

    if cached_mtime != estat.st_mtime:
        return cache_proc_env(pid, epath, estat.st_mtime)

    return proc_env_cache[pid]


def get_caller_pid():
    uid, gid, pid = fuse_get_context()
    return pid


class EnvLinkFS(Operations):

    def getattr(self, path, fh=None):
        if path == '/':
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
            }

        var = path[1:]

        try:
            get_proc_env(get_caller_pid())[var]
        except KeyError:
            raise FuseOSError(errno.ENOENT)

        return {
            'st_mode': stat.S_IFLNK | 0o444,
            'st_nlink': 1,
        }

    def readdir(self, path, fh):
        if path != '/':
            raise FuseOSError(errno.ENOENT)

        yield '.'
        yield '..'

        for var, val in get_proc_env(get_caller_pid()).items():
            try:
                os.lstat(val)
            except FileNotFoundError:
                continue
            except OSError as e:
                if e.errno == errno.ENAMETOOLONG:
                    continue

            yield var

    def readlink(self, path):
        try:
            return get_proc_env(get_caller_pid())[path[1:]]
        except KeyError:
            raise FuseOSError(errno.ENOENT)


def main():
    import argparse

    p = argparse.ArgumentParser()

    p.add_argument('fsname',
        metavar='FSNAME',
        help="name of the filesystem (shows up in 'mount')"
    )

    p.add_argument('mountpoint',
        metavar='MOUNTPOINT',
        help="where to mount the filesystem",
    )

    p.add_argument('-f', '--foreground',
        action='store_true',
        help="foreground operation"
    )

    p.add_argument('-d', '--debug',
        action='store_true',
        help="enable debug output (implies -f)"
    )

    p.add_argument('-s', '--single-thread',
        action='store_true',
        help="disable multi-threaded operation"
    )

    p.add_argument('-o', '--options',
        metavar='OPTIONS',
        default='',
        help="FUSE mount options"
    )

    args = p.parse_args()
    kwargs = {}

    # parse the option string into key:value pairs...
    # ... which fusepy will then un-parse back into an option string,
    # and pass it to fuse_main
    #
    # *headdesk*

    for opt in args.options.split(','):
        if '=' in opt:
            key, val = opt.split('=', 1)
            kwargs[key] = val
        else:
            kwargs[opt] = True

    kwargs['fsname'] = args.fsname

    FUSE(
        operations=EnvLinkFS(),
        mountpoint=args.mountpoint,
        foreground=args.foreground,
        debug=args.debug,
        nothreads=args.single_thread,
        **kwargs
    )

if __name__ == '__main__':
    main()
