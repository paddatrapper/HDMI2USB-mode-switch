#!/usr/bin/env python3
# vim: set ts=4 sw=4 et sts=4 ai:

"""
Functions needed by hdmi2usb-mode-switch implemented using lsusb and other
Linux command line tools.

This will only run on Linux.
"""

import os
import re
import subprocess

from hdmi2usb_common import *

SYS_ROOT = '/sys/bus/usb/devices'

def get_path_from_sysdir(dirpath):
    buspath = os.path.join(dirpath, 'busnum')
    devpath = os.path.join(dirpath, 'devnum')
    if not os.path.exists(buspath):
        logging.info("Skipping %s (no busnum)", dirname)
        return None
    if not os.path.exists(devpath):
        logging.info("Skipping %s (no devnum)", dirname)
        return None

    busnum = int(open(buspath, 'r').read().strip())
    devnum = int(open(devpath, 'r').read().strip())

    return Path(bus=busnum, address=devnum)


def create_sys_mapping():
    # 1-1.3.1  --> (Device)    bus-port.port.port
    # 1-0:1.0  --> (Interface) bus-port.port.port:config.interface
    # usb1     --> bus<number>

    devices = {}
    interfaces = {}

    dirs = list(sorted(os.listdir(SYS_ROOT)))
    for dirname in dirs:
        dirpath = os.path.join(SYS_ROOT, dirname)
        if ":" in dirname:
            continue
        path = get_path_from_sysdir(dirpath)
        assert path
        devices[dirpath] = path
        assert path not in interfaces
        interfaces[path] = [dirpath]

    for dirname in dirs:
        dirpath = os.path.join(SYS_ROOT, dirname)
        if ":" not in dirname:
            continue

        device, interface = dirname.split(':')
        if device.endswith('-0'):
            device = "usb%s" % (device[:-2])

        devpath = os.path.join(SYS_ROOT, device)
        assert os.path.exists(devpath)
        assert devpath in devices

        interfaces[devices[devpath]].append(dirpath)

    return interfaces


FIND_SYS_CACHE = {}
def find_sys(path, mapping=FIND_SYS_CACHE):
    if not mapping:
        mapping.update(create_sys_mapping())
    return mapping[path]


class LsusbDevice(DeviceBase):
    def __new__(cls, *args, **kw):
        syspaths = find_sys(kw['path'])
        syspaths.sort()

        # Get the did number from sysfs
        didpath = os.path.join(syspaths[0], "bcdDevice")
        if not os.path.exists(didpath):
            did = None
        else:
            did = open(didpath, "r").read().strip()

        # Get the did number from sysfs
        serialnopath = os.path.join(syspaths[0], "serial")
        if not os.path.exists(serialnopath):
            serialno = None
        else:
            serialno = open(serialnopath, "r").read().strip()

        d = DeviceBase.__new__(cls, *args, did=did, serialno=serialno, **kw)
        d.syspaths = syspaths
        return d

    def __repr__(self):
        if self.serialno:
            s = repr(self.serialno)
        else:
            s = self.path
        return "%s(%04x:%04x:%s %s)" % (
            self.__class__.__name__, self.vid, self.pid, self.did, s)

    def inuse(self):
        return bool(self.drivers())

    def drivers(self):
        drivers = {}
        for path in self.syspaths[1:]:
            driver_path = os.path.join(path, "driver")
            if os.path.exists(driver_path):
                drivers[path] = os.readlink(driver_path)
        return tuple(set(d.split('/')[-1] for d in drivers.values()))

    def detach(self):
        for path in self.syspaths[1:]:
            driver_path = os.path.join(path, "driver")
            if os.path.exists(driver_path):
                unbind_path = os.path.join(driver_path, "unbind")
                assert os.path.exists(unbind_path), unbind_path
                interface = os.path.split(path)[-1]
                try:
                    open(unbind_path, "w").write(interface)
                except PermissionError:
                    subprocess.check_call("bin/unbind-helper '%s' '%s'" % (unbind_path, interface), shell=True)

    def tty(self):
        ttys = []
        for path in self.syspaths:
            tty_path = os.path.join(path, "tty")
            if os.path.exists(tty_path):
                names = list(os.listdir(tty_path))
                assert len(names) == 1
                ttys.append('/dev/'+names[0])
        return ttys


Device = LsusbDevice


def find_usb_devices():
    FIND_SYS_CACHE.clear()

    # 'Bus 002 Device 002: ID 8087:0024 Intel Corp. Integrated Rate Matching Hub'
    lsusb_device_regex = re.compile(
        "Bus (?P<bus>[0-9]+) Device (?P<address>[0-9]+):"
        " ID (?P<vid>[0-9a-f]+):(?P<pid>[0-9a-f]+)")

    devobjs = []
    output = subprocess.check_output('lsusb')
    for line in output.splitlines():
        line = line.decode('utf-8')
        bits = lsusb_device_regex.match(line)
        assert bits, repr(line)

        vid = int(bits.group('vid'), base=16)
        pid = int(bits.group('pid'), base=16)
        bus = int(bits.group('bus'), base=10)
        address = int(bits.group('address'), base=10)
        devobjs.append(LsusbDevice(
            vid=vid, pid=pid, path=Path(bus=bus, address=address),
            ))

    return devobjs
