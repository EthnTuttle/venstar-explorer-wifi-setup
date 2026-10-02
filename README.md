# Venstar Explorer WiFi setup without the Skyport app

How Venstar Explorer-series thermostats (the four-button **Mode / Fan / ▲ / ▼**
Explorer Mini, and the larger Explorer with a WiFi module) receive their WiFi
credentials. Includes a small dependency-free Python script that does the same
thing as the Skyport app's "set up Wi-Fi on a new device" flow, so you can
put a thermostat on your network from a laptop without a Venstar cloud
account.

The protocol was recovered by static analysis of the Venstar Skyport Android
app (`air.com.venstar.skyport`, v7.4.1), and then tested on real hardware.

Not affiliated with or endorsed by Venstar.

## Tested

| Model string | Unit | Result |
|---|---|---|
| `XPM-T2000-3.02-VEN` | Explorer Mini T2000 (×2) | Provisioned onto a WPA2 network; Local API reachable afterwards |

Other Explorer models share the same app code path but have not been tested.
Reports are welcome.

## Quick start (Explorer Mini)

1. **Put the thermostat in setup mode:** hold **FAN** for 5 seconds. When
   *Wireless Setup* appears, release and press **▼** (the app calls it
   "Cooler").
2. **Join its hotspot:** connect your computer to the network
   `THERMOSTAT-XXXX` (the suffix is the last 3 bytes of its MAC). The
   password is `123456789`. You'll get an address in `192.168.1.0/24`. The
   thermostat is `192.168.1.1`.
3. **Run the script:**
   ```sh
   ./venstar_provision.py info                 # model / MAC / firmware (read-only)
   ./venstar_provision.py scan                 # networks the thermostat can see (read-only)
   ./venstar_provision.py config "MyNetwork" - # prompts for the password, no echo
   ./venstar_provision.py complete             # leave setup mode and join WiFi
   ```
   `config` printing `{1000: [126], ...}` means SUCCESS (126). FAILURE is
   127. `complete` returns `{"success" : true}`, the hotspot disappears and
   the thermostat joins your network via DHCP.
4. **Rejoin your own WiFi** and find the thermostat (DHCP leases, or
   `curl http://<ip>/query/info` once Local API is on).

Use a 2.4 GHz network. The radio is a TI CC3220SF.

For the full-size **Explorer (T3xxx/T4xxx)**, which requires an ACC-VWF1 or
ACC-VWF2 WiFi module, enter setup mode with **ACCESSORY SETUP** (under the
front door) and then **Cooler**. The app also sends a device name before the
WiFi config on those models (`./venstar_provision.py name "Den"`).

### After provisioning

The thermostat menu's **Skyport / Local API / Time API** toggles are separate
from setup mode, and that menu has no WiFi option. Turn on **Local API** to
use Venstar's documented local HTTP API (`/query/info`, `/control`,
`/settings` on port 80). Home Assistant's built-in `venstar` integration
uses that API.

Cloud pairing is optional and only needed for the Skyport app. On the Mini,
hold FAN for 5 seconds and press **▲** ("Warmer") to show a pairing code.

## Protocol

### Transport

- **Soft-AP:**
  - SSID prefix: `THERMOSTAT` for thermostats, `SENSOR` for Venstar WiFi
    sensors.
  - WPA/WPA2, fixed PSK `123456789`.
- **Address:** HTTP on `http://192.168.1.1:8190`.
- **Body:** every request and response body is a 4-byte big-endian length
  followed by a protobuf (proto2) `setupMode.Message`. The schema is in
  [`proto/setup_mode.proto`](proto/setup_mode.proto). The app sends no
  special Content-Type.

### Message

```
Message {
  required Commands command  = 1000;   // enum
  required string   sequence = 1001;   // the app always sends "Venstar"
  oneof data { ... }                   // payload field number == command number
}
```

Commands used during setup:

| # | Name | Direction | Payload |
|---|---|---|---|
| 2 | `LOGIN` | reply to `GET /info` | `mac`(1) `fwVer`(2) `model`(3) `name`(4) |
| 16 | `NAME` | request | `name`(1), max 15 chars |
| 120 | `WIFICONFIG` | request | `SSID`(1) `securityType`(2) `dhcp`(3) `password`(4); static only: `ipv4Address`(5) `mask`(6) `gateway`(7) `dnsAddress`(8) as uint32 |
| 121 | `WIFISCANRESULTS` | request (empty) / reply | repeated `{SSID(1), securityType(2), signalStrength(3)}` |
| 122 / 123 | `ENTERPRISE_CONFIG` / `CERTCHUNK` | request | WPA2-Enterprise (EAP method, identity, certs). Not implemented here |
| 126 / 127 | `SUCCESS` / `FAILURE` | reply | `FAILURE`: `code`(1) `msg`(2) |

- `securityType` values: `0` None, `1` WEP, `2` WPA, `3` WPA2. The password
  is omitted when the type is None.
- `signalStrength` is an unsigned byte; dBm = value − 256.

### Sequence (as the app does it)

1. `GET /info` returns `LOGIN`.
2. `POST /command` with `WIFISCANRESULTS` returns the scan list.
3. Set the name (full Explorer / Base Station only):
   - normally `POST /command` with `NAME`;
   - the "explorer2" and Base Station firmware families use
     `POST /settings` with `deviceName=<name>` (form-encoded) instead.
4. `POST /command` with `WIFICONFIG` returns `SUCCESS`/`FAILURE`.
5. `POST /completed` (empty body) returns `{"success" : true}`. The
   thermostat leaves setup mode.

### Example

`WIFICONFIG` for SSID `MyWiFi`, password `secret123`, WPA2, DHCP:

```
00000027                                   length = 39
c207 17 0a064d7957694669 1003 1801         field 120: SSID, securityType=3, dhcp=1
        2209736563726574313233             password
c03e 78                                    command = 120
ca3e 07 56656e73746172                     sequence = "Venstar"
```

`./venstar_provision.py selftest` prints this. protobufjs produces the same
bytes when encoding with `proto/setup_mode.proto`.

### Other findings

- **Discovery:** the Skyport app does no LAN discovery (no SSDP or mDNS).
  After setup it only talks to thermostats through Venstar's cloud
  (`api.skyportcloud.com`, `wss.skyportcloud.com`). LAN discovery
  (SSDP `venstar:thermostat:ecp`) is part of the separate Local API.
- **WiFi sensors** (`SENSOR-XXXX`) use JSON endpoints instead:
  - `/sensorinfo` and `/scanResults`;
  - `/command/wificonfig`, `/command/name` and `/command/complete`.

  These are not covered by the script.
- **Model families:** the app's model families, by its brand config:
  - **Explorer Mini:** T2000, T2001, T2010, T2011, T2050, T2060, T2061,
    T2100, T2110, T2150, T2151, T2160.
  - **Explorer ("Voyager" internally):** T3700, T3800, T3900, T3950/T3951-IAQ,
    T4700, T4800, T4900, T4900SCH, T4950/T4951/T4975-IAQ.
  - **Base Station:** 3951B.
  - **Explorer FlatStat.**

## Security note

The setup hotspot uses a fixed, published password, and the WiFi credentials
travel to the thermostat over plain HTTP on that network. Anyone in radio
range while a unit is in *Wireless Setup* mode can join and read them. Keep
setup mode short. The thermostat leaves it after `complete`.

## License

MIT. See [LICENSE](LICENSE).
