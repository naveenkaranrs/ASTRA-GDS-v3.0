"""
Mission Control Dashboard - Satellite Hardware-in-the-Loop Simulator
=====================================================================
Generates high-fidelity simulated telemetry at 2Hz (or configurable rate)
and publishes JSON frames to MQTT topic `mission/node_alpha`.

Usage:
    python mock_simulator.py [--broker broker.emqx.io] [--port 1883] [--rate 2.0]
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
    parser = argparse.ArgumentParser(description="Satellite Hardware-in-the-Loop Telemetry Simulator")
    parser.add_argument("--broker", type=str, default="broker.emqx.io", help="MQTT Broker Host (default: broker.emqx.io)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker Port (default: 1883)")
    parser.add_argument("--topic", type=str, default="mission/node_alpha", help="MQTT Topic (default: mission/node_alpha)")
    parser.add_argument("--rate", type=float, default=2.0, help="Publish frequency in Hz (default: 2.0)")
    parser.add_argument("--node-id", type=str, default="NODE-ALPHA", help="Spacecraft Node Identifier")
    return parser.parse_args()


class SatelliteSimulator:
    """Simulates physical dynamics and sensor telemetry for an orbital satellite."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.sequence_id = 0
        self.start_time = time.time()
        
        # Orbital Parameters (ISS-like 51.6° Inclination LEO orbit)
        self.orbit_period = 360.0  # seconds per full orbit revolution
        self.inclination = 51.64   # degrees
        self.base_altitude = 412.5 # km
        self.base_velocity = 7.662 # km/s
        self.orbit_number = 1420

    def generate_packet(self) -> Dict[str, Any]:
        self.sequence_id += 1
        elapsed = time.time() - self.start_time
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # 1. Orbital Kinematics
        orbit_phase = (elapsed % self.orbit_period) / self.orbit_period * 2.0 * math.pi
        latitude = self.inclination * math.sin(orbit_phase)
        longitude = (((elapsed * (360.0 / self.orbit_period) * 1.5) + 45.0) % 360.0) - 180.0
        altitude = self.base_altitude + 3.8 * math.cos(orbit_phase * 2) + random.gauss(0, 0.08)
        velocity = self.base_velocity + 0.035 * math.sin(orbit_phase) + random.gauss(0, 0.005)
        is_sunlit = math.sin(orbit_phase) > -0.15

        # 2. ADCS 6-DOF Attitude Dynamics
        pitch = 14.5 * math.sin(elapsed * 0.35) + 2.5 * math.sin(elapsed * 1.4) + random.gauss(0, 0.2)
        roll = 22.0 * math.cos(elapsed * 0.28) + 3.1 * math.cos(elapsed * 0.9) + random.gauss(0, 0.3)
        yaw = (elapsed * 8.5 + 4.0 * math.sin(elapsed * 0.4) + random.gauss(0, 0.15)) % 360.0

        gyro_x = round(14.5 * 0.35 * math.cos(elapsed * 0.35) + random.gauss(0, 0.05), 2)
        gyro_y = round(-22.0 * 0.28 * math.sin(elapsed * 0.28) + random.gauss(0, 0.05), 2)
        gyro_z = round(8.5 + random.gauss(0, 0.04), 2)

        # 3. EPS Power Subsystem
        sunlight_factor = max(0.0, math.sin(orbit_phase))
        solar_power_w = round(152.0 * sunlight_factor + (random.gauss(0, 1.2) if is_sunlit else 0), 1)
        battery_pct = min(100.0, max(25.0, 78.0 + 20.0 * sunlight_factor + random.gauss(0, 0.15)))
        battery_voltage_v = round(11.2 + 1.35 * (battery_pct / 100.0) + random.gauss(0, 0.02), 2)
        current_draw_a = round(2.65 + 0.35 * math.sin(elapsed * 0.15) + random.gauss(0, 0.04), 2)

        # 4. TCS Thermal Subsystem
        temp_internal = round(28.0 + 9.5 * sunlight_factor + 1.2 * math.sin(elapsed * 0.04) + random.gauss(0, 0.1), 2)
        temp_external = round(-22.0 + 78.0 * sunlight_factor + random.gauss(0, 0.4), 2)

        # 5. Comms & RF Link
        rssi = round(-68.5 + 10.5 * math.sin(elapsed * 0.08) + random.gauss(0, 0.8), 1)
        link_quality = min(100, max(10, int((rssi + 110) * (100 / 60))))
        packet_loss = round(max(0.0, 0.1 + 0.05 * math.sin(elapsed * 0.05) + random.gauss(0, 0.02)), 2)
        ping_ms = round(18.0 + 8.0 * math.sin(elapsed * 0.12) + random.gauss(0, 1.5), 1)

        payload = {
            "node_id": self.node_id,
            "seq": self.sequence_id,
            "timestamp": now_utc.isoformat(),
            "met_seconds": round(elapsed, 1),
            "orbital": {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "altitude_km": round(altitude, 2),
                "velocity_kms": round(velocity, 3),
                "orbit_number": self.orbit_number + int(elapsed // self.orbit_period),
                "sunlit": is_sunlit
            },
            "adcs": {
                "pitch": round(pitch, 2),
                "roll": round(roll, 2),
                "yaw": round(yaw, 2),
                "gyro_x": gyro_x,
                "gyro_y": gyro_y,
                "gyro_z": gyro_z,
                "mode": "SUN_POINTING" if is_sunlit else "NADIR_TRACK"
            },
            "power": {
                "solar_power_w": max(0.0, solar_power_w),
                "battery_pct": round(battery_pct, 1),
                "battery_voltage_v": battery_voltage_v,
                "current_draw_a": current_draw_a,
                "bus_status": "NOMINAL"
            },
            "thermal": {
                "temp_internal_c": temp_internal,
                "temp_external_c": temp_external,
                "heaters_active": not is_sunlit
            },
            "comm": {
                "downlink_freq_mhz": 437.450,
                "rssi_dbm": rssi,
                "link_quality_pct": link_quality,
                "packet_loss_pct": packet_loss,
                "ping_ms": ping_ms
            },
            # Flat aliases for direct binding
            "pitch": round(pitch, 2),
            "roll": round(roll, 2),
            "yaw": round(yaw, 2),
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "altitude": round(altitude, 2),
            "velocity": round(velocity, 3),
            "temperature": temp_internal,
            "battery_voltage": battery_voltage_v,
            "attitude": {
                "pitch": round(pitch, 2),
                "roll": round(roll, 2),
                "yaw": round(yaw, 2),
                "rates": {"gx": gyro_x, "gy": gyro_y, "gz": gyro_z}
            },
            "orbit": {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "altitude_km": round(altitude, 2),
                "velocity_kms": round(velocity, 3),
                "sunlit": is_sunlit
            },
            "environment": {
                "temperature_internal_c": temp_internal,
                "temperature_external_c": temp_external
            },
            "system_health": {
                "overall": "GREEN",
                "adcs": "NOMINAL",
                "eps": "NOMINAL",
                "tcs": "NOMINAL",
                "comm": "NOMINAL"
            },
            "predictive": {
                "soc_slope_pct_min": -0.12,
                "time_to_crit_min": 360,
                "confidence_pct": 96,
                "recommended_action": "Maintain nominal flight profile."
            },
            "xai": {
                "observed_deviation_pct": 0,
                "confidence_pct": 96,
                "shap_weights": {"eps": 0.45, "tcs": 0.25, "payload": 0.18, "solar": 0.12},
                "probable_causes": [
                    {"cause": "Payload Power Overload", "prob_pct": 82},
                    {"cause": "Solar Array Degradation", "prob_pct": 12},
                    {"cause": "Battery Cell Imbalance", "prob_pct": 6}
                ]
            },
            "stm": {
                "conjunction_active": False,
                "debris_id": "DEBRIS-4821",
                "miss_distance_m": 3400.0,
                "collision_prob": 0.00002,
                "tca_seconds": 245
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
    print("=" * 72)
    print(" [*] SATELLITE HARDWARE-IN-THE-LOOP SIMULATOR (NODE-ALPHA)")
    print("=" * 72)
    print(f" Target Node ID  : {args.node_id}")
    print(f" MQTT Broker     : {args.broker}:{args.port}")
    print(f" Telemetry Topic : {args.topic}")
    print(f" Publish Rate    : {args.rate} Hz ({1.0/args.rate:.2f}s interval)")
    print("=" * 72)

    client_id = f"HIL_Simulator_{args.node_id}_{int(time.time())}"
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
            print(f"[+] Connected to broker [{args.broker}:{args.port}]")
        else:
            print(f"[-] Connection failed. Return code: {rc_val}")

    client.on_connect = on_connect

    try:
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[!] MQTT connection error: {e}")

    simulator = SatelliteSimulator(node_id=args.node_id)
    interval = 1.0 / args.rate

    print("\n[>>] Streaming live telemetry to 'mission/node_alpha'...\n")
    try:
        while True:
            t0 = time.time()
            packet = simulator.generate_packet()
            payload_json = json.dumps(packet)

            # Publish to primary topic and fallback topic
            client.publish(args.topic, payload_json, qos=1)
            client.publish("mission/telemetry/node1", payload_json, qos=1)

            orb = packet["orbital"]
            adcs = packet["adcs"]
            pwr = packet["power"]
            th = packet["thermal"]
            cm = packet["comm"]

            print(
                f"[#{packet['seq']:05d} | MET {packet['met_seconds']:>5.1f}s] "
                f"LAT:{orb['latitude']:>7.2f}° LON:{orb['longitude']:>7.2f}° ALT:{orb['altitude_km']:>5.1f}km | "
                f"P:{adcs['pitch']:>5.1f}° R:{adcs['roll']:>5.1f}° Y:{adcs['yaw']:>5.1f}° | "
                f"BAT:{pwr['battery_pct']:>4.1f}% ({pwr['battery_voltage_v']}V) | "
                f"SOLAR:{pwr['solar_power_w']:>5.1f}W | "
                f"TEMP:{th['temp_internal_c']:>4.1f}°C | "
                f"RSSI:{cm['rssi_dbm']:>5.1f}dBm"
            )

            elapsed = time.time() - t0
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[*] Telemetry generation stopped by operator.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
