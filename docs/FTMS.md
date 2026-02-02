# FTMS relay server overview

This module provides a BLE Fitness Machine Service (FTMS) relay that bridges
BLE clients to iFit equipment via `IFitBleClient`.

## Data flow

1. The relay connects to iFit equipment and reads equipment limits to populate
   supported speed and incline range characteristics.
2. A Bless-based GATT server advertises FTMS with read, write, notify, and
   indicate characteristics for treadmill data and the control point.
3. A periodic async loop reads current iFit values (speed, incline, distance,
   heart rate, mode) and publishes FTMS treadmill data notifications.
4. Fitness Machine Status is derived from iFit `Mode` and emitted when the
   treadmill transitions between active and paused/idle states.

## Control point handling

The relay supports a minimal subset of FTMS control point commands:

- Request control
- Set target speed (0.01 km/h resolution)
- Set target incline (0.1% resolution)

Control point writes are validated, decoded, and forwarded to the iFit client.
The relay responds with FTMS response codes for success, invalid parameters,
unsupported opcodes, and operation failures.

## FTMS helper module

The `ftms.py` module centralizes FTMS UUIDs, opcodes, result codes, and encoding
helpers for treadmill data, supported ranges, and status values.
