# iFit BLE Protocol Structure

This document provides a comprehensive explanation of the iFit BLE protocol structure used for communicating with iFit-enabled fitness equipment (treadmills, bikes, ellipticals, etc.) over Bluetooth Low Energy.

## Table of Contents

- [Overview](#overview)
- [BLE Connection](#ble-connection)
- [Protocol Layers](#protocol-layers)
- [Message Structure](#message-structure)
- [Commands](#commands)
- [Characteristics](#characteristics)
- [Data Types and Converters](#data-types-and-converters)
- [Request/Response Flow](#requestresponse-flow)
- [Examples](#examples)

---

## Overview

The iFit BLE protocol is a proprietary protocol used by iFit-enabled fitness equipment to:

- Control equipment parameters (speed, incline, resistance, etc.)
- Monitor equipment state (current values, mode, workout stats)
- Discover equipment capabilities
- Authenticate and unlock equipment for control

The protocol uses a custom framing scheme over standard BLE GATT characteristics, with messages split into chunks to fit BLE's 20-byte MTU limitation.

---

## BLE Connection

### Service and Characteristics

The iFit protocol uses a custom BLE service with two characteristics:

- **Service UUID**: `000015331412efde1523785feabcd123`
- **RX Characteristic UUID**: `000015351412efde1523785feabcd123` (client writes commands to equipment)
- **TX Characteristic UUID**: `000015341412efde1523785feabcd123` (client receives responses from equipment)

### Connection Flow

1. **Scan** for BLE devices advertising the iFit service UUID
2. **Connect** to the device
3. **Discover services** (may need to wait for device reconfiguration)
4. **Subscribe** to TX characteristic notifications
5. **Authenticate** using activation code (for control) or skip (for monitoring)
6. **Discover** equipment capabilities
7. **Send commands** and receive responses

---

## Protocol Layers

The iFit protocol has three distinct layers:

```
┌─────────────────────────────────┐
│   BLE Framing Layer             │  ← Splits messages into 20-byte chunks
├─────────────────────────────────┤
│   Command Protocol Layer        │  ← Encodes commands, checksums, equipment ID
├─────────────────────────────────┤
│   Data Encoding Layer           │  ← Characteristic values, bitmaps, converters
└─────────────────────────────────┘
```

---

## Message Structure

### Layer 1: BLE Framing

BLE has a 20-byte MTU (Maximum Transmission Unit), but the first 2 bytes are used for framing metadata, leaving 18 bytes for payload data per chunk.

#### Header Chunk

The first chunk of every request/response:

```
┌────┬────┬────┬────┐
│ FE │ 02 │ LL │ NN │
└────┴────┴────┴────┘
  0    1    2    3

FE = Message header marker (0xFE = MessageIndex.HEADER)
02 = Fixed value
LL = Total length of the raw request/response (before chunking)
NN = Total number of chunks (including this header chunk)
```

#### Payload Chunks

Subsequent chunks contain actual data:

```
┌────┬────┬──────────────────────┐
│ TT │ LL │ <payload bytes>      │
└────┴────┴──────────────────────┘
  0    1    2-19 (up to 18 bytes)

TT = Chunk index (0, 1, 2...) or 0xFF (MessageIndex.EOF) for final chunk
LL = Number of payload bytes in this chunk (max 18)
```

**Example**: A 40-byte request is split into:

- 1 header chunk (4 bytes)
- 2 payload chunks (18 bytes each)
- 1 final chunk (4 bytes, marked with 0xFF)

### Layer 2: Command Protocol

The raw command payload (before chunking):

```
┌────┬────┬────┬────┬────┬────┬────┬──────────┬────┐
│ 02 │ 04 │ 02 │ LL │ EE │ LL │ CC │ PAYLOAD  │ SS │
└────┴────┴────┴────┴────┴────┴────┴──────────┴────┘
  0    1    2    3    4    5    6    7...      -1

Bytes 0-2: Fixed prefix (0x02, 0x04, 0x02) - iFit protocol signature
Byte 3:    LL = Payload length + 4
Byte 4:    EE = Equipment identifier (SportsEquipment enum)
Byte 5:    LL = Payload length + 4 (repeated)
Byte 6:    CC = Command identifier (Command enum)
Bytes 7+:  Command-specific payload
Last byte: SS = Checksum (low byte of sum of EE + LL + CC + all payload bytes)
```

#### Equipment Identifiers

| Value | Name       | Description          |
|-------|------------|----------------------|
| 0x02  | GENERAL    | Generic equipment    |
| 0x04  | TREADMILL  | Treadmill-specific   |

#### Command Identifiers

| Value | Name                   | Description                                |
|-------|------------------------|--------------------------------------------|
| 0x02  | WRITE_AND_READ         | Set/get characteristic values (most common)|
| 0x06  | CALIBRATE              | Calibrate sensors (e.g., incline)          |
| 0x80  | SUPPORTED_CAPABILITIES | Query supported features                   |
| 0x81  | EQUIPMENT_INFORMATION  | Get equipment metadata                     |
| 0x82  | EQUIPMENT_REFERENCE    | Get reference number                       |
| 0x84  | EQUIPMENT_FIRMWARE     | Get firmware version                       |
| 0x88  | SUPPORTED_COMMANDS     | Query supported commands                   |
| 0x90  | ENABLE                 | Authenticate/unlock equipment              |
| 0x95  | EQUIPMENT_SERIAL       | Get serial number                          |

**Typical initialization sequence**: 0x81 → 0x80 → 0x88 → 0x82 → 0x84 → 0x95 → 0x90

### Layer 3: Data Encoding

The command payload contains:

- **Bitmaps**: Indicate which characteristics are being written/read
- **Values**: Encoded characteristic values in ascending ID order
- **Metadata**: Command-specific data

---

## Commands

### ENABLE (0x90) - Authentication

Unlocks equipment for control using an activation code.

**Payload**: 36-byte activation code (binary)

**Example**: For activation code `0102030405060708...` (36 bytes = 72 hex chars), send those bytes directly as the payload.

### EQUIPMENT_INFORMATION (0x81) - Discover Characteristics

Queries which characteristics the equipment supports.

**Payload**: None

**Response** (starting at byte 16):

```
┌────┬──────────────────────┐
│ LL │ bitmap bytes         │
└────┴──────────────────────┘

LL = Number of bitmap bytes
Bitmap: Each bit represents a characteristic ID (bit 0 = ID 0, bit 1 = ID 1, etc.)
```

**Example characteristics bitmap**:

```
Byte 0 (bits 0-7):   IDs 0-7   (Kph, Incline, ..., Unknown)
Byte 1 (bits 0-7):   IDs 8-15  (Unknown, Volume, Pulse, UpTime, Mode, ...)
...
```

### EQUIPMENT_REFERENCE (0x82) - Get Reference Number

Retrieves the device reference number.

**Payload**: `00 00`

**Response Structure**:

```
┌────┬────┬────┬────┬────┬────┬─────────┬─────┬─────────────────┬───────────┐
│ 01 │ 04 │ 02 │ LL │ 04 │ LL │ FLAGS.. │ ... │ REF (LE 4-byte) │ ...       │
└────┴────┴────┴────┴────┴────┴─────────┴─────┴─────────────────┴───────────┘
  0    1    2    3    4    5    6-7      ...       15-18             19+

Byte 0-1:   Header (0104)
Byte 2:     Sub-command (02)
Byte 3:     Length indicator
Byte 4:     Device type (04 or 07)
Byte 5:     Length repeated
Byte 6-14:  Metadata/flags
Byte 15-18: Reference number (little-endian 4-byte integer)
Byte 19+:   Additional data
```

**Example**:

- Input: `01040221042182026400014d2409002cfe0500780036e8030024f400f40101000102000061`
- Reference at bytes 15-18: `2cfe0500` = 392748 (decimal)

### EQUIPMENT_FIRMWARE (0x84) - Get Firmware Version

Retrieves the firmware version string.

**Payload**: `00 00`

**Response Structure**:

```
┌────┬────┬────┬────┬────┬────┬──────────┬────┬─────────────────┐
│ 01 │ 04 │ 02 │ LL │ 04 │ LL │ FLAGS... │ ?? │ ASCII String... │
└────┴────┴────┴────┴────┴────┴──────────┴────┴─────────────────┘
  0    1    2    3    4    5    6-10      11+   Firmware version

Byte 0-1:   Header (0104)
Byte 2:     Sub-command (02)
Byte 3:     Length indicator
Byte 4:     Device type (04 or 07)
Byte 5-10:  Metadata/flags
Byte 11+:   ASCII firmware version string (terminated by control char \x01 or \x00)
```

**Example**:

- Input: `0104021c041c840250a300302e312e30363132323031372e30393038012a0316`
- Firmware from byte 11: `0.1.06122017.0908`

### EQUIPMENT_SERIAL (0x95) - Get Serial Number

Retrieves the device serial number.

**Payload**: `00 00`

**Response Structure**:

```
┌────┬────┬────┬────┬────┬────┬───────┬────┬────┬────────────────────┬────┐
│ 01 │ 04 │ 02 │ LL │ 04 │ ?? │ FLAGS │ ?? │ LN │ ASCII Serial...    │ CS │
└────┴────┴────┴────┴────┴────┴───────┴────┴────┴────────────────────┴────┘
  0    1    2    3    4    5    6-7     8    9    10+                 -1

Byte 0-1:   Header (0104)
Byte 2:     Sub-command (02)
Byte 3:     Length indicator
Byte 4:     Device type (04 or 07)
Byte 5-7:   Metadata/flags
Byte 8:     Serial string length (LN, e.g., 0x12 = 18 chars)
Byte 9+:    ASCII serial number string (LN bytes)
Last byte:  Checksum

Serial Format: ######-MODEL### (e.g., 393647-MM74Z57555)
```

### SUPPORTED_CAPABILITIES (0x80) - Discover Features

Queries high-level capabilities (Speed, Incline, Pulse, etc.).

**Payload**: None

**Response** (starting at byte 8):

```
┌────┬──────────────────┐
│ NN │ capability IDs   │
└────┴──────────────────┘

NN = Number of capabilities
Each subsequent byte is a capability ID
```

**Common capability mappings**:

| Capability ID | Name     | Characteristic ID |
|---------------|----------|-------------------|
| 65 (0x41)     | Speed    | 0                 |
| 66 (0x42)     | Incline  | 1                 |
| 70 (0x46)     | Pulse    | 10                |
| 71 (0x47)     | Key      | 7                 |
| 77 (0x4D)     | Distance | 6                 |
| 78 (0x4E)     | Time     | 11                |

### WRITE_AND_READ (0x02) - Control and Monitor

The most common command - simultaneously sets values (write) and retrieves values (read).

**Payload Structure**:

```
┌─────────────┬────────────┬────────────────┐
│ Write bitmap│ Read bitmap│ Write values   │
└─────────────┴────────────┴────────────────┘
```

#### Bitmap Structure

Each bitmap encodes which characteristics are included:

```
┌────┬──────────────────────┐
│ LL │ bitmap bytes         │
└────┴──────────────────────┘

LL = Number of bitmap bytes that follow
Each bit indicates if that characteristic ID is included
```

**Example**: Request characteristics 0, 1, 4, 10

```
Characteristic IDs: 0, 1, 4, 10

Byte 0 (IDs 0-7):   0b00010011 = 0x13  (bits 0, 1, 4 set)
Byte 1 (IDs 8-15):  0b00000100 = 0x04  (bit 2 = ID 10 set)

Bitmap: [0x02, 0x13, 0x04]
        ^^^^  ^^^^  ^^^^
         LL   Byte0 Byte1
```

#### Write Values Encoding

After the read bitmap, write values are appended **in ascending characteristic ID order**, using each characteristic's converter.

**Example**: Write Kph=5.5 (ID 0) and Incline=3.0 (ID 1)

```
Kph (ID 0):     5.5 → 550 (×100) → [0x26, 0x02] (little-endian uint16)
Incline (ID 1): 3.0 → 300 (×100) → [0x2C, 0x01] (little-endian uint16)

Write values: [0x26, 0x02, 0x2C, 0x01]
```

#### Read Values Response

Response contains read values **in ascending characteristic ID order**, starting at byte 8.

**Example response**:

```
Bytes 0-7:  Protocol header
Bytes 8-9:  Kph value (2 bytes)
Bytes 10-11: Incline value (2 bytes)
Bytes 12-15: CurrentDistance value (4 bytes)
Bytes 16-19: Pulse value (4 bytes)
...
Last byte:  Checksum
```

---

## Characteristics

Characteristics represent equipment parameters and state. Each has:

- **ID**: Unique numeric identifier (0-255)
- **Name**: Human-readable name
- **Read-only**: Whether it can be written
- **Converter**: Data type and encoding/decoding functions

### Common Characteristics

#### Control Characteristics (Writable)

| ID | Name    | Data Type | Size | Description      |
|----|---------|-----------|------|------------------|
| 0  | Kph     | Double    | 2    | Target speed     |
| 1  | Incline | Double    | 2    | Target incline   |
| 9  | Volume  | UInt8     | 1    | Audio volume     |
| 12 | Mode    | UInt8     | 1    | Equipment mode   |
| 36 | Metric  | Boolean   | 1    | Metric units     |

#### Read-Only Characteristics (Status/Sensors)

| ID | Name            | Data Type | Size | Description            |
|----|-----------------|-----------|------|------------------------|
| 4  | CurrentDistance | UInt32    | 4    | Distance traveled (m)  |
| 6  | Distance        | UInt32    | 4    | Total distance         |
| 10 | Pulse           | Composite | 4    | Heart rate data        |
| 11 | UpTime          | UInt32    | 4    | Equipment uptime (sec) |
| 13 | Calories        | Scaled32  | 4    | Total calories         |
| 16 | CurrentKph      | Double    | 2    | Actual speed           |
| 17 | CurrentIncline  | Double    | 2    | Actual incline         |
| 20 | CurrentTime     | UInt32    | 4    | Workout time (sec)     |
| 21 | CurrentCalories | Scaled32  | 4    | Calories burned        |

#### Equipment Limits

| ID | Name       | Data Type | Size | Description   |
|----|------------|-----------|------|---------------|
| 27 | MaxIncline | Double    | 2    | Max incline % |
| 28 | MinIncline | Double    | 2    | Min incline % |
| 30 | MaxKph     | Double    | 2    | Max speed     |
| 31 | MinKph     | Double    | 2    | Min speed     |
| 49 | MaxPulse   | UInt8     | 1    | Max heart rate|

#### Summary/Statistics

| ID  | Name           | Data Type | Size | Description           |
|-----|----------------|-----------|------|-----------------------|
| 52  | AverageIncline | Double    | 2    | Average incline %     |
| 70  | TotalTime      | UInt32    | 4    | Total workout time    |
| 103 | PausedTime     | UInt32    | 4    | Time paused           |

### Equipment Modes

| Value | Name               | Description               |
|-------|--------------------|---------------------------|
| 0     | UNKNOWN            | Unknown state             |
| 1     | IDLE               | Equipment idle/ready      |
| 2     | ACTIVE             | Workout in progress       |
| 3     | PAUSE              | Workout paused            |
| 4     | SUMMARY            | Showing workout summary   |
| 7     | SETTINGS           | In settings menu          |
| 8     | MISSING_SAFETY_KEY | Safety key not inserted   |

---

## Data Types and Encoding

Characteristics are encoded using specific data types. All multi-byte integers use **little-endian** byte order.

### Data Types

| Type      | Size | Encoding                                              | Example                          |
|-----------|------|-------------------------------------------------------|----------------------------------|
| UInt8     | 1    | Unsigned 8-bit integer (0-255)                        | 10 → `0A`                        |
| UInt16    | 2    | Unsigned 16-bit integer, little-endian                | 1000 → `E8 03`                   |
| UInt32    | 4    | Unsigned 32-bit integer, little-endian                | 123456 → `40 E2 01 00`           |
| Boolean   | 1    | Boolean flag (0x00 = false, 0x01 = true)              | true → `01`                      |
| Double    | 2    | Scaled UInt16 with 2 decimal places (value × 100)     | 5.5 → 550 → `26 02`              |
| Scaled32  | 4    | Scaled UInt32 for calories (value × 1024 / 100000000) | 100.0 → 9765625 → `89 0F 95 00`  |
| Composite | 4    | Multi-field structure (see Pulse below)               | See pulse encoding               |

### Pulse Data Structure (4 bytes)

Pulse data is encoded as a 4-byte composite structure:

```
┌─────────┬─────────┬───────┬────────┐
│ Byte 0  │ Byte 1  │ Byte 2│ Byte 3 │
├─────────┼─────────┼───────┼────────┤
│ Current │ Average │ Count │ Source │
│ BPM     │ BPM     │       │        │
└─────────┴─────────┴───────┴────────┘
```

**Pulse Source Values**:

| Value | Source               |
|-------|----------------------|
| 0x00  | No heart rate        |
| 0x01  | Hand grip sensors    |
| 0x02  | Unknown              |
| 0x03  | Unknown              |
| 0x04  | BLE heart rate monitor|

---

## Communication Flow

### Typical Session Flow

1. **Connect** to BLE device and subscribe to TX characteristic
2. **Discover capabilities** (send 0x81, 0x80, 0x88 commands)
3. **Retrieve metadata** (send 0x82, 0x84, 0x95 for reference, firmware, serial)
4. **Authenticate** (send 0x90 with activation code) - required for control, optional for monitoring
5. **Control/Monitor** (send 0x02 commands to write/read characteristics)

### Monitor-Only Mode

For read-only monitoring, skip the ENABLE (0x90) command and only use WRITE_AND_READ (0x02) with:

- Empty write bitmap (no values to set)
- Read bitmap specifying characteristics to monitor
- No write values payload

---

## Examples

### Example 1: Set Speed to 10 km/h

**Goal**: Write characteristic 0 (Kph) = 10.0, no reads

**Step 1: Build payload**

```
Write bitmap: [0x01, 0x01]  (1 byte, bit 0 set for char ID 0)
Read bitmap:  [0x00]        (no reads)
Write value:  10.0 → 1000 → [0xE8, 0x03]  (Double encoding)

Payload: 01 01 00 E8 03
```

**Step 2: Build command frame**

```
02 04 02    Signature
09          Length (5 bytes payload + 4)
04          Equipment (TREADMILL)
09          Length (repeated)
02          Command (WRITE_AND_READ)
01 01 00 E8 03  Payload
05          Checksum (0x04+0x09+0x02+0x01+0x01+0x00+0xE8+0x03 = 0x105 → 0x05)
```

**Step 3: Split into BLE chunks**

```
Chunk 0 (Header): FE 02 0D 01  (0xFE, reserved, length=13, chunks=1)
Chunk 1 (Data):   FF 0D 02 04 02 09 04 09 02 01 01 00 E8 03 05  (0xFF=EOF, len=13, data)
```

### Example 2: Monitor Current State

**Goal**: Read characteristics 4, 10, 16, 17, 20 (no writes)

**Build bitmap for IDs 4, 10, 16, 17, 20**:

```
Byte 0 (IDs 0-7):   bit 4 set       → 0b00010000 = 0x10
Byte 1 (IDs 8-15):  bit 2 set       → 0b00000100 = 0x04  (ID 10)
Byte 2 (IDs 16-23): bits 0,1,4 set  → 0b00010011 = 0x13  (IDs 16,17,20)

Read bitmap: [0x03, 0x10, 0x04, 0x13]  (3 bytes, then bitmap bytes)
```

**Request payload**:

```
Write bitmap: [0x00]               (no writes)
Read bitmap:  [0x03, 0x10, 0x04, 0x13]
```

**Response data** (starting at byte 8, in ascending ID order):

```
Bytes  8-11: 40 E2 01 00  → CurrentDistance (ID 4)  = 123456 (UInt32)
Bytes 12-15: 78 50 0A 04  → Pulse (ID 10)           = {120 BPM, avg 80, count 10, BLE}
Bytes 16-17: 2C 01        → CurrentKph (ID 16)      = 3.0 km/h (Double)
Bytes 18-19: 58 02        → CurrentIncline (ID 17)  = 6.0% (Double)
Bytes 20-23: 78 00 00 00  → CurrentTime (ID 20)     = 120 seconds (UInt32)
```

### Example 3: Complete Session

**1. Discovery Phase**

```
Send 0x81: EQUIPMENT_INFORMATION  → Get bitmap of supported characteristics
Send 0x80: SUPPORTED_CAPABILITIES → Get list of capability IDs
Send 0x88: SUPPORTED_COMMANDS     → Get list of supported command IDs
```

**2. Metadata Phase** (optional)

```
Send 0x82: EQUIPMENT_REFERENCE → Get device reference number (4 bytes at offset 15-18)
Send 0x84: EQUIPMENT_FIRMWARE  → Get firmware string (ASCII at offset 11+)
Send 0x95: EQUIPMENT_SERIAL    → Get serial number (length at byte 8, string at 9+)
```

**3. Authentication** (required for control)

```
Send 0x90: ENABLE with 36-byte activation code payload
```

**4. Control Loop**

```
• Send 0x02 to write Kph=8.0, Incline=2.0
• Send 0x02 to read CurrentKph, CurrentIncline, Pulse, CurrentDistance, CurrentTime
• Repeat as needed
```

---

## Summary

The iFit BLE protocol is a three-layer binary protocol:

### Protocol Layers

1. **BLE Framing Layer**
   - Splits messages into 20-byte chunks (18 bytes data + 2 bytes metadata)
   - Header chunk: `FE 02 LL NN` (length, chunk count)
   - Data chunks: `II LL <data>` (index/EOF, length, payload)

2. **Command Protocol Layer**
   - Fixed signature: `02 04 02`
   - Length, equipment ID, command ID
   - Command-specific payload
   - Checksum (low byte of sum)

3. **Data Encoding Layer**
   - Bitmaps indicate which characteristics are included
   - Values encoded by data type (little-endian)
   - Values ordered by ascending characteristic ID

### Key Protocol Features

- **17 Commands**: Discovery (0x80, 0x81, 0x88), metadata (0x82, 0x84, 0x95), control (0x02, 0x90, 0x06)
- **100+ Characteristics**: Equipment parameters with typed encoding (UInt8/16/32, Double, Boolean, Composite)
- **Bitmap Encoding**: Efficient specification of characteristic sets
- **Checksum Validation**: Simple sum-based integrity checking
- **Authentication**: 36-byte activation code for control access (monitoring doesn't require auth)

This protocol supports both **control** (setting speed, incline, etc.) and **monitoring** (reading current state) of iFit fitness equipment over Bluetooth Low Energy.
