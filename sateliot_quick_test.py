#!/usr/bin/env python3
"""
SatelIoT NTN modem configuration and test script.
Sends a sequence of AT commands to configure a nRF9151 modem for NTN connectivity.

Usage:
    python scripts/sateliot_quick_test.py --port COM3
    python scripts/sateliot_quick_test.py --port COM3 --baud 115200
    python scripts/sateliot_quick_test.py --port COM3 --lat -30.033 --lon -51.229
    python scripts/sateliot_quick_test.py --port COM3 --save session --timestamp
"""

import argparse
import csv
import queue
import re
import serial
import sys
import threading
import time
from datetime import datetime

# ANSI Colors
GRAY   = "\033[90m"
RESET  = "\033[0m"
GREEN  = "\033[92m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
RED    = "\033[91m"

# Default observer location: Porto Alegre, Brazil
DEFAULT_LAT = "-30.065361"
DEFAULT_LON = "-51.235283"
DEFAULT_ALT = "50"

# Timeouts (seconds)
DEFAULT_TIMEOUT = 3.0
CFUN1_TIMEOUT   = 30.0

# Shared state (initialised in main())
stop_event      = None
response_queue  = None
command_pending = None
log_file        = None
args            = None


# ─── AT Command Groups ──────────────────────────────────────────────────────

INIT_COMMANDS = [
    ("AT+CGMM",      "Model identification"),
    ("AT%HWVERSION", "Hardware version"),
    ("AT+CGMR",      "Firmware revision"),
    ("AT+CFUN=0",    "Disable modem (full power off)"),
]

# AT%LOCATION is inserted dynamically after args
SATELIOT_CONFIG_COMMANDS = [
    ("AT+COPS=1,2,\"90197\"",                 "Select SatelIoT operator manually (PLMN 90197)"),
    ("AT%XSYSTEMMODE=0,0,0,0,1",              "Set NTN-only system mode"),
    ("AT%XBANDLOCK=2,,\"256\"",               "Lock to NTN band 256"),
    ("AT%PERIODICSEARCHCONF=0,1,0,0,\"1,2\"", "Configure periodic cell search"),
]

NOTIFICATION_COMMANDS = [
    ("AT+CEREG=5",  "Enable extended network registration URC"),
    ("AT+CSCON=3",  "Enable signaling connection status URC"),
    ("AT%CESQ=1",   "Enable signal quality URC"),
    ("AT%MDMEV=2",  "Enable modem events"),
    ("AT+CNEC=24",  "Enable network error codes"),
    ("AT+CGEREP=1", "Enable packet domain event reporting"),
]

CONNECT_COMMANDS = [
    ("AT+CFUN=1", "Enable modem (full functionality)"),
]


# ─── Logging ────────────────────────────────────────────────────────────────

def log_message(message):
    """Print to console and optionally write to log file, with optional timestamp."""
    if args.timestamp:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"{GRAY}[{ts}]{RESET} {message}")
        if log_file:
            clean = re.sub(r'\033\[[0-9;]*m', '', f"[{ts}] {message}")
            log_file.write(clean + '\n')
            log_file.flush()
    else:
        print(message)
        if log_file:
            clean = re.sub(r'\033\[[0-9;]*m', '', message)
            log_file.write(clean + '\n')
            log_file.flush()


# ─── URC Decoders ───────────────────────────────────────────────────────────

def decode_cesq(line):
    """Decode %CESQ: <rsrp>,<rsrp_thr>,<rsrq>,<rsrq_thr> → human-readable string."""
    try:
        if not line.startswith("%CESQ:"):
            return None
        values = [int(x.strip()) for x in line.split(":", 1)[1].split(",")]
        if len(values) != 4:
            return None
        rsrp, rsrp_thr, rsrq, rsrq_thr = values

        rsrp_thresholds = ["<20", "20-39", "40-59", "60-79", "≥80"]
        rsrq_thresholds = ["<7",  "7-13",  "14-20", "21-27", "≥28"]

        if rsrp == 255:
            rsrp_info = "RSRP: 255 (Invalid)"
        else:
            rsrp_dbm  = rsrp - 141
            thr_desc  = rsrp_thresholds[rsrp_thr] if 0 <= rsrp_thr <= 4 else "Unknown"
            rsrp_info = f"RSRP: {rsrp} ({rsrp_dbm} dBm, threshold: {thr_desc})"

        if rsrq == 255:
            rsrq_info = "RSRQ: 255 (Invalid)"
        else:
            rsrq_db   = (rsrq - 40) / 2
            thr_desc  = rsrq_thresholds[rsrq_thr] if 0 <= rsrq_thr <= 4 else "Unknown"
            rsrq_info = f"RSRQ: {rsrq} ({rsrq_db} dB, threshold: {thr_desc})"

        return f"{rsrp_info}, {rsrq_info}"
    except (ValueError, IndexError):
        return None


def decode_cereg(line):
    """Decode +CEREG: URC → human-readable registration status string."""
    try:
        if not line.startswith("+CEREG:"):
            return None
        values_part = line.split(":", 1)[1].strip()
        values = [v.strip().strip('"') for v in list(csv.reader([values_part]))[0]]
        if not values:
            return None

        status_desc = {
            "0":  "Not registered (not searching)",
            "1":  "Registered (home network)",
            "2":  "Not registered (searching/attaching)",
            "3":  "Registration denied",
            "4":  "Unknown (out of coverage)",
            "5":  "Registered (roaming)",
            "50": "Not registered, not searching (receiver-only)",
            "51": "Registered, home network (receiver-only)",
            "52": "Not registered, searching (receiver-only)",
            "53": "Registration denied (receiver-only)",
            "54": "Unknown (receiver-only)",
            "55": "Registered, roaming (receiver-only)",
            "90": "Not registered (UICC failure)",
            "91": "Not registered (no suitable cell for configured system mode)",
        }
        act_desc = {
            "7":  "LTE-M",
            "9":  "NB-IoT",
            "14": "NTN NB-IoT",
        }

        stat   = values[0]
        result = f"Status: {stat} ({status_desc.get(stat, f'Unknown ({stat})')})"

        if len(values) >= 4:
            tac, ci, act = values[1], values[2], values[3]
            if tac or ci:
                result += f", TAC: {tac or '-'}, Cell ID: {ci or '-'}"
            if act:
                result += f", AcT: {act} ({act_desc.get(act, f'Unknown ({act})')})"
        return result
    except Exception:
        return None


def decode_cscon(line):
    """Decode +CSCON: URC → human-readable signaling connection string."""
    try:
        if not line.startswith("+CSCON:"):
            return None
        values = [v.strip() for v in line.split(":", 1)[1].split(",")]
        if not values:
            return None

        mode_desc   = {"0": "Idle", "1": "Connected"}
        state_desc  = {"7": "E-UTRAN connected"}
        access_desc = {"4": "Radio access of type E-UTRAN FDD"}

        mode   = values[0]
        result = f"Mode: {mode} ({mode_desc.get(mode, f'Unknown ({mode})')})"

        if len(values) >= 2 and values[1]:
            s = values[1]
            result += f", State: {s} ({state_desc.get(s, f'Unknown ({s})')})"
        if len(values) >= 3 and values[2]:
            a = values[2]
            result += f", Access: {a} ({access_desc.get(a, f'Unknown ({a})')})"
        return result
    except Exception:
        return None


# ─── URC Printer ─────────────────────────────────────────────────────────────

def _ts_indent():
    """Alignment indent to match the timestamp prefix width."""
    return " " * 26 if args.timestamp else ""


def _decode_and_format(s):
    """Return (colored_line, decoded_annotation_or_None) for a response/URC line."""
    if s.startswith("%CESQ:"):
        return f"{CYAN}{s}{RESET}", decode_cesq(s)
    elif s.startswith("+CEREG:"):
        return f"{GREEN}{s}{RESET}", decode_cereg(s)
    elif s.startswith("+CSCON:"):
        return f"{BLUE}{s}{RESET}", decode_cscon(s)
    elif s == "OK":
        return f"{GREEN}{s}{RESET}", None
    elif s.startswith("ERROR") or s.startswith("+CME ERROR") or s.startswith("+CMS ERROR"):
        return f"{RED}{s}{RESET}", None
    else:
        return f"{CYAN}{s}{RESET}", None


def print_urc(line):
    """Print an unsolicited result code with colour and decode annotation."""
    s = line.strip()
    colored, decoded = _decode_and_format(s)
    msg = colored
    if decoded:
        msg += f"\n{GRAY}{_ts_indent()}→ {decoded}{RESET}"
    log_message(msg)


# ─── Threading Layer ─────────────────────────────────────────────────────────

def _urc_reader(ser):
    """Background thread: reads every line from the serial port.

    Lines are routed to response_queue while a command is pending; otherwise
    they are printed immediately as URCs.
    """
    ser.timeout = 0.1
    while not stop_event.is_set():
        try:
            line = ser.readline().decode(errors="replace").strip()
        except serial.SerialException:
            break
        if not line:
            continue
        if command_pending.is_set():
            response_queue.put(line)
        else:
            print_urc(line)


def send_at(ser, cmd, desc="", timeout=DEFAULT_TIMEOUT):
    """Send an AT command, print the response lines, and return them as a list."""
    header = f"{YELLOW}> {cmd}{RESET}"
    if desc:
        header += f"  {GRAY}# {desc}{RESET}"
    log_message(header)

    command_pending.set()
    ser.write((cmd + "\r\n").encode())

    lines    = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = response_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        s = line.strip()
        colored, decoded = _decode_and_format(s)
        msg = colored
        if decoded:
            msg += f"\n{GRAY}{_ts_indent()}→ {decoded}{RESET}"
        log_message(msg)
        lines.append(s)

        if s in ("OK", "ERROR") or s.startswith("+CME ERROR") or s.startswith("+CMS ERROR"):
            break

    command_pending.clear()
    time.sleep(0.05)
    return lines


# ─── Setup Sequence ──────────────────────────────────────────────────────────

def run_setup(ser, lat, lon, alt):
    """Execute the full SatelIoT NTN setup sequence in four phases."""
    log_message(f"\n{YELLOW}{'='*50}{RESET}")
    log_message(f"{YELLOW}  SatelIoT NTN Setup{RESET}")
    log_message(f"{YELLOW}{'='*50}{RESET}")

    log_message(f"\n{YELLOW}--- Phase 1: Modem Information ---{RESET}")
    for cmd, desc in INIT_COMMANDS:
        send_at(ser, cmd, desc)

    log_message(f"\n{YELLOW}--- Phase 2: SatelIoT NTN Configuration ---{RESET}")
    for cmd, desc in SATELIOT_CONFIG_COMMANDS:
        send_at(ser, cmd, desc)

    location_cmd = f'AT%LOCATION=2,"{lat}","{lon}","{alt}",0,0'
    send_at(ser, location_cmd, "Set NTN observer location")

    log_message(f"\n{YELLOW}--- Phase 3: Enable Notifications ---{RESET}")
    for cmd, desc in NOTIFICATION_COMMANDS:
        send_at(ser, cmd, desc)

    log_message(f"\n{YELLOW}--- Phase 4: Connect ---{RESET}")
    for cmd, desc in CONNECT_COMMANDS:
        send_at(ser, cmd, desc, timeout=CFUN1_TIMEOUT)

    log_message(f"\n{GREEN}Setup complete.{RESET}")


# ─── Interactive Shell ────────────────────────────────────────────────────────

def interactive_shell(ser):
    """Interactive AT command shell with URC decode."""
    log_message(f"\n{YELLOW}=== Interactive Mode ==={RESET}")
    log_message(f"{YELLOW}Type any AT command, or 'exit' / Ctrl+C to quit.{RESET}\n")

    try:
        while True:
            try:
                user_input = input(f"{BLUE}> {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() == "exit":
                break

            cmd = user_input
            if not cmd.upper().startswith("AT"):
                cmd = "AT" + cmd
            send_at(ser, cmd)

    except KeyboardInterrupt:
        pass
    finally:
        log_message(f"\n{YELLOW}Exiting interactive mode.{RESET}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global stop_event, response_queue, command_pending, log_file, args

    parser = argparse.ArgumentParser(
        description="Configure nRF9151 modem for SatelIoT NTN and monitor URCs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-p", "--port",  required=True,
                        help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    parser.add_argument("-b", "--baud",  type=int, default=115200,
                        help="Baud rate")
    parser.add_argument("--lat",         default=DEFAULT_LAT,
                        help="Observer latitude")
    parser.add_argument("--lon",         default=DEFAULT_LON,
                        help="Observer longitude")
    parser.add_argument("--alt",         default=DEFAULT_ALT,
                        help="Observer altitude in meters")
    parser.add_argument("-s", "--save",  metavar="NAME",
                        help="Log to NAME_YYYYMMDD_HHMMSS.log")
    parser.add_argument("--timestamp",   action="store_true",
                        help="Prefix every message with a timestamp")
    args = parser.parse_args()

    # ── Logging setup ──
    if args.save:
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{args.save}_{ts}.log"
        log_file     = open(log_filename, 'w', encoding='utf-8')
        print(f"Logging to: {log_filename}")

    # ── Threading state ──
    stop_event      = threading.Event()
    response_queue  = queue.Queue()
    command_pending = threading.Event()

    # ── Open serial port ──
    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
    except serial.SerialException as exc:
        print(f"{RED}ERROR: Could not open {args.port}: {exc}{RESET}")
        sys.exit(1)

    time.sleep(0.5)
    ser.reset_input_buffer()

    # ── Start background reader ──
    reader = threading.Thread(target=_urc_reader, args=(ser,), daemon=True)
    reader.start()

    # Disable modem echo so echoed bytes don't appear as response lines
    command_pending.set()
    ser.write(b"ATE0\r\n")
    time.sleep(0.5)
    while True:
        try:
            response_queue.get_nowait()
        except queue.Empty:
            break
    command_pending.clear()

    try:
        log_message(f"\n{YELLOW}SatelIoT NTN Test Script{RESET}")
        log_message(f"{YELLOW}Port: {args.port}  Baud: {args.baud}{RESET}")
        log_message(f"\n{YELLOW}Location: Lat={args.lat}, Lon={args.lon}, Alt={args.alt}m{RESET}")

        run_setup(ser, args.lat, args.lon, args.alt)

        log_message(f"\n{YELLOW}URCs are decoded in real-time. Type commands below.{RESET}")
        interactive_shell(ser)

    except KeyboardInterrupt:
        log_message(f"\n{YELLOW}Interrupted by user.{RESET}")
    finally:
        stop_event.set()
        if log_file:
            log_file.close()
        ser.close()
        print("Port closed.")


if __name__ == "__main__":
    main()
