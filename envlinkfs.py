#!/usr/bin/env python3

import os
import sys
import errno
import stat
import ctypes
import fuse
import functools
import contextlib

from fuse import (
    FUSE,
    FuseOSError,
    Operations,
    fuse_get_context,
)

from signal import signal, SIGINT, SIG_DFL


proc_env_cache = {}
proc_env_cache_times = {}


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


class DirectFUSE(FUSE):

    '''
    Partial copypaste and simplification of the FUSE.__init__ method.
    This lets us pass arguments to FUSE directly on the command line.
    '''

    def __init__(self, operations, args, raw_fi=False, encoding='utf-8'):
        '''
        Setting raw_fi to True will cause FUSE to pass the fuse_file_info
        class as is to Operations, instead of just the fh field.
        This gives you access to direct_io, keep_cache, etc.
        '''

        self.operations = operations
        self.raw_fi = raw_fi
        self.encoding = encoding

        args = [arg.encode(encoding) for arg in args]
        argv = (ctypes.c_char_p * len(args))(*args)

        fuse_ops = fuse.fuse_operations()
        for ent in fuse.fuse_operations._fields_:
            name, prototype = ent[:2]

            val = getattr(operations, name, None)
            if val is None:
                continue

            # Function pointer members are tested for using the
            # getattr(operations, name) above but are dynamically
            # invoked using self.operations(name)
            if hasattr(prototype, 'argtypes'):
                val = prototype(functools.partial(self._wrapper, getattr(self, name)))

            setattr(fuse_ops, name, val)

        try:
            old_handler = signal(SIGINT, SIG_DFL)
        except ValueError:
            old_handler = SIG_DFL

        err = fuse._libfuse.fuse_main_real(
            len(args), argv, ctypes.pointer(fuse_ops), ctypes.sizeof(fuse_ops), None)

        try:
            signal(SIGINT, old_handler)
        except ValueError:
            pass

        del self.operations     # Invoke the destructor

        if err:
            quit(err)


def main():
    DirectFUSE(EnvLinkFS(), sys.argv)

if __name__ == '__main__':
    main()
