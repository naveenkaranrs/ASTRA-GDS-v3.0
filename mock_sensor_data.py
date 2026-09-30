"""
Mission Control Dashboard - Mock Sensor Telemetry Generator
============================================================
Simulates realistic orbital hardware telemetry (IMU, Thermal, Orbital Coordinates, Power)
and publishes JSON payloads to the configured MQTT broker.

Usage:
    python mock_sensor_data.py [--broker broker.emqx.io] [--port 1883] [--rate 2.0]
"""

import sys
import time
import math
import json
import random
import argparse
import datetime
from typing import Dict, Any

import paho.mqtt.client as mqtt

def parse_args():
    parser = argparse.ArgumentParser(description="Mock Aerospace Sensor Data Generator")
    parser.add_argument("--broker", type=str, default="broker.emqx.io", help="MQTT Broker Host (default: broker.emqx.io)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker Port (default: 1883)")
    parser.add_argument("--topic", type=str, default="mission/telemetry/node1", help="MQTT Topic (default: mission/telemetry/node1)")
    parser.add_argument("--rate", type=float, default=2.0, help="Publish frequency in Hz (default: 2.0)")
    parser.add_argument("--node-id", type=str, default="AERO-NODE-01", help="Hardware Node Identifier")
    return parser.parse_args()


class TelemetrySimulator:
    """Simulates physical dynamics and sensor telemetry for an orbital spacecraft."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.sequence_id = 0
        self.start_time = time.time()
        
        # Orbital Simulation Parameters (ISS-like 51.6° Inclination LEO)
        self.orbit_period = 300.0  # Accelerated orbital period in seconds for demo purposes
        self.inclination = 51.64   # degrees
        self.base_altitude = 412.5 # km
        self.base_velocity = 7.66  # km/s
        self.epoch_start = datetime.datetime.now(datetime.timezone.utc)

    def generate_packet(self) -> Dict[str, Any]:
        self.sequence_id += 1
        elapsed = time.time() - self.start_time
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # 1. IMU Attitude Dynamics (Oscillatory orbital motion + sensor noise)
        pitch = 18.5 * math.sin(elapsed * 0.4) + 3.0 * math.sin(elapsed * 1.8) + random.gauss(0, 0.3)
        roll = 28.0 * math.cos(elapsed * 0.3) + 4.2 * math.cos(elapsed * 1.2) + random.gauss(0, 0.4)
        yaw = (elapsed * 12.0 + 5.0 * math.sin(elapsed * 0.5) + random.gauss(0, 0.2)) % 360.0

        # Gyro Angular Rates (deg/s)
        gyro_x = round(18.5 * 0.4 * math.cos(elapsed * 0.4) + random.gauss(0, 0.1), 2)
        gyro_y = round(-28.0 * 0.3 * math.sin(elapsed * 0.3) + random.gauss(0, 0.1), 2)
        gyro_z = round(12.0 + random.gauss(0, 0.05), 2)

        # 2. Orbital Coordinates & Dynamics (LEO ground track)
        orbit_phase = (elapsed % self.orbit_period) / self.orbit_period * 2.0 * math.pi
        latitude = self.inclination * math.sin(orbit_phase)
        # Longitude sweeps from -180 to 180 degrees
        longitude = ((elapsed * (360.0 / self.orbit_period) * 1.5) % 360.0) - 180.0
        altitude = self.base_altitude + 4.5 * math.cos(orbit_phase * 2) + random.gauss(0, 0.05)
        velocity = self.base_velocity + 0.04 * math.sin(orbit_phase) + random.gauss(0, 0.01)

        # 3. Thermal Subsystem (°C)
        is_sunlit = math.sin(orbit_phase) > -0.2
        sunlight_factor = max(0.0, math.sin(orbit_phase))
        internal_temp = 28.5 + 10.0 * sunlight_factor + 1.5 * math.sin(elapsed * 0.05) + random.gauss(0, 0.15)
        external_temp = -25.0 + 85.0 * sunlight_factor + random.gauss(0, 0.5)

        # 4. Electrical Power Subsystem (EPS)
        battery_voltage = 11.4 + 1.2 * sunlight_factor + random.gauss(0, 0.03)
        battery_percent = min(100.0, max(20.0, 72.0 + 26.0 * sunlight_factor + random.gauss(0, 0.2)))
        solar_array_power = round(145.0 * sunlight_factor + (random.gauss(0, 1.5) if is_sunlit else 0), 1)
        system_current_draw = round(2.8 + 0.4 * math.sin(elapsed * 0.2), 2)

        # 5. Radio Communication & Signal Quality
        rssi = -74.0 + 12.0 * math.sin(elapsed * 0.1) + random.gauss(0, 1.2)

        # 6. Subsystem Health Checks
        status_imu = "NOMINAL" if abs(pitch) < 85 else "WARNING"
        status_thermal = "NOMINAL" if internal_temp < 45.0 else "WARNING"
        status_power = "NOMINAL" if battery_percent > 30.0 else "CRITICAL"

        payload = {
            "node_id": self.node_id,
            "seq": self.sequence_id,
            "timestamp": now_utc.isoformat(),
            "epoch": round(time.time(), 3),
            "met_seconds": round(elapsed, 1),
            "attitude": {
                "pitch": round(pitch, 2),
                "roll": round(roll, 2),
                "yaw": round(yaw, 2),
                "rates": {
                    "gx": gyro_x,
                    "gy": gyro_y,
                    "gz": gyro_z
                }
            },
            "orbit": {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "altitude_km": round(altitude, 2),
                "velocity_kms": round(velocity, 3),
                "sunlit": is_sunlit
            },
            "environment": {
                "temperature_internal_c": round(internal_temp, 2),
                "temperature_external_c": round(external_temp, 2),
                "pressure_kpa": 101.32
            },
            "power": {
                "battery_voltage_v": round(battery_voltage, 2),
                "battery_level_pct": round(battery_percent, 1),
                "solar_power_w": max(0.0, solar_array_power),
                "current_draw_a": system_current_draw
            },
            "comms": {
                "rssi_dbm": round(rssi, 1),
                "link_quality_pct": min(100, max(0, int((rssi + 110) * (100 / 60)))),
                "frequency_mhz": 437.450
            },
            "system_health": {
                "overall": "GREEN" if status_power == "NOMINAL" and status_thermal == "NOMINAL" else "YELLOW",
                "imu": status_imu,
                "power": status_power,
                "thermal": status_thermal,
                "nav": "NOMINAL"
            }
        }
        return payload


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()
    print("=" * 70)
    print(" [>] AEROSPACE HARDWARE TELEMETRY SIMULATOR")
    print("=" * 70)
    print(f" Target Node    : {args.node_id}")
    print(f" MQTT Broker    : {args.broker}:{args.port}")
    print(f" Telemetry Topic: {args.topic}")
    print(f" Publish Rate   : {args.rate} Hz ({1.0/args.rate:.2f}s interval)")
    print("=" * 70)

    # Initialize MQTT Client
    client_id = f"MockSensorSimulator_{args.node_id}_{int(time.time())}"
    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True
        )
    except AttributeError:
        client = mqtt.Client(client_id=client_id, clean_session=True)

    def on_connect(cli, userdata, flags, rc, properties=None):
        rc_val = rc if isinstance(rc, int) else getattr(rc, "value", rc)
        if rc_val == 0:
            print(f"[+] Connected successfully to broker [{args.broker}:{args.port}]")
        else:
            print(f"[-] Failed to connect to broker. Return code: {rc_val}")

    client.on_connect = on_connect

    try:
        print(f"[*] Connecting to {args.broker}:{args.port}...")
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[!] Error establishing MQTT connection: {e}")
        print("[!] Retrying connection in background...")

    simulator = TelemetrySimulator(node_id=args.node_id)
    interval = 1.0 / args.rate

    print("\n[>>] Starting live telemetry generation. Press Ctrl+C to abort.\n")
    try:
        while True:
            t0 = time.time()
            packet = simulator.generate_packet()
            payload_json = json.dumps(packet)

            # Publish to MQTT topic
            result = client.publish(args.topic, payload_json, qos=1)

            # Formatted terminal display
            att = packet["attitude"]
            orb = packet["orbit"]
            env = packet["environment"]
            pwr = packet["power"]

            print(
                f"[#{packet['seq']:05d} | MET {packet['met_seconds']:>5.1f}s] "
                f"PITCH:{att['pitch']:>6.1f}° | ROLL:{att['roll']:>6.1f}° | YAW:{att['yaw']:>5.1f}° "
                f"| TEMP:{env['temperature_internal_c']:>5.1f}°C "
                f"| LAT:{orb['latitude']:>7.2f}° LON:{orb['longitude']:>7.2f}° ALT:{orb['altitude_km']:>5.1f}km "
                f"| BAT:{pwr['battery_level_pct']:>4.1f}%"
            )

            # Calculate sleep duration to maintain exact target rate
            elapsed = time.time() - t0
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[*] Telemetry generation halted by operator.")
    finally:
        client.loop_stop()
        client.disconnect()
        print("[*] MQTT connection terminated gracefully.")


if __name__ == "__main__":
    main()
