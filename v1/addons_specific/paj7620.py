# paj7620.py
# Driver for the PAJ7620U2 gesture sensor.
#
# Based on CircuitPython driver by Radomir Dopieralski (MIT)
# Ported to MicroPython for CYD project.
#
# PAJ7620 requires a wake-up write before it will respond on I2C.
# SoftI2C with timeout=100_000 required (device clock-stretches on wake-up).
#
# Reliable gestures (empirically verified): UP, DOWN, LEFT, RIGHT, NEAR, FAR.
# CW, CCW, WAVE are defined but unreliable with this init configuration.

import time

UP    = 0x001
DOWN  = 0x002
LEFT  = 0x004
RIGHT = 0x008
NEAR  = 0x010
FAR   = 0x020
CW    = 0x040  # unreliable
CCW   = 0x080  # unreliable
WAVE  = 0x100  # unreliable

# Inherited init sequence from Radomir Dopieralski's CircuitPython driver.
# Configures internal processing parameters across bank 0 and bank 1.
# 0xEF entries embedded in the sequence are bank-select writes.
_ADDR = (
    b"\xefAB789BFGHIJLQ^`\x80\x81\x82\x8b\x90\x95\x96\x97\x9a\x9c"
    b"\xa5\xcc\xcd\xce\xcf\xd0\xef\x02\x03\x04%'()>^egijmnrstw\xef"
    b"AB"
)
_DATA = (
    b"\x00\x00\x00\x07\x17\x06\x01-\x0f<\x00\x1e\"\x10\x10'BD\x04"
    b"\x01\x06\n\x0c\x05\x14?\x19\x19\x0b\x13d!\x01\x0f\x10\x02\x01"
    b"9\x7f\x08\xff=\x96\x97\xcd\x01,\x01\x015\x00\x01\x00\xff\x01"
)


class PAJ7620:

    def __init__(self, i2c, addr=0x73):
        self._i2c = i2c
        self._addr = addr
        self._wake()
        # Verify chip ID before running init sequence.
        # OSError here means the device is absent; _wake() cannot distinguish
        # an expected NACK from a missing device, so this read is the real check.
        self._write(0xEF, 0x00)  # bank 0
        id0 = self._read1(0x00)
        id1 = self._read1(0x01)
        if id0 != 0x20 or id1 != 0x76:
            raise OSError("PAJ7620 not found (ID 0x{:02X} 0x{:02X})".format(id0, id1))
        for reg, val in zip(_ADDR, _DATA):
            self._write(reg, val)

    def _wake(self):
        try:
            self._i2c.writeto(self._addr, b'\x00')
        except OSError:
            pass
        time.sleep_ms(2)

    def _write(self, reg, val):
        self._i2c.writeto_mem(self._addr, reg, bytes([val]))

    def _read1(self, reg):
        return self._i2c.readfrom_mem(self._addr, reg, 1)[0]

    def read(self):
        """Poll for gesture flags. Returns bitmask; test with e.g. `raw & UP`.
        Multiple bits may be set on a single read. Returns 0 when idle.
        Registers clear on read."""
        data = self._i2c.readfrom_mem(self._addr, 0x43, 2)
        return int.from_bytes(data, 'little')
