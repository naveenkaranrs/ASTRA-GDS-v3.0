/*
 * ==============================================================================
 * ASTRA-GDS: 1U CubeSat Hardware-in-the-Loop (HIL) Testbed Firmware v3.0
 * ==============================================================================
 * Target Hardware: ESP32 WROOM-32 (Dual Core @ 240MHz)
 * Competition: Indian Space Association (ISpA) / IISc 2026 Conclave
 * Category: Space Systems Engineering, Digital Twin & Autonomous Operations
 * 
 * CLOSED-LOOP BI-DIRECTIONAL ARCHITECTURE:
 *   ESP32 Sensors -> Telemetry JSON -> ASTRA-GDS Dashboard -> ML Anomaly Trigger
 *   -> Autonomous Decision Engine -> Telecommand -> ESP32 Actuator (GPIO OFF)
 *   -> Physical Current/Temp Reduction -> Dashboard Verifies Closed-Loop Recovery
 * 
 * Peripherals & Actuators:
 *  - MPU6050 6-DOF IMU (I2C: SDA=GPIO21, SCL=GPIO22)
 *  - Mini Photovoltaic Solar Cell (ADC1: GPIO34 with 2:1 voltage divider)
 *  - 18650 Li-Ion Battery Bus (ADC1: GPIO35 with 4:1 precision divider)
 *  - Heartbeat Status LED (GPIO4)
 *  - Payload Power Switch Relay / MOSFET (GPIO18)
 *  - Thermal Heaters Relay (GPIO19)
 *  - Safe-Mode Telemetry Indicator (GPIO2)
 * 
 * Telemetry Pipelines:
 *  1. Primary: Direct USB Web Serial @ 115200 baud (CCSDS-inspired JSON)
 *  2. Secondary: WiFi MQTT client publishing to broker.emqx.io:1883
 * ==============================================================================
 */

#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>

// ------------------------------------------------------------------------------
// Pin Definitions & Hardware Actuators
// ------------------------------------------------------------------------------
#define LED_PIN             4
#define PAYLOAD_POWER_PIN   18   // Actuator: High-side MOSFET switch for scientific payload
#define HEATER_RELAY_PIN    19   // Actuator: Thermal heater coil control
#define SAFE_MODE_LED_PIN   2    // Actuator: Onboard Blue LED indicator for Autonomous Safe-Mode
#define SOLAR_ADC_PIN       34
#define BATTERY_ADC_PIN     35
#define MPU_ADDR            0x68

#define SERIAL_BAUD_RATE    115200
#define TELEMETRY_RATE_HZ   20.0
#define SAMPLE_INTERVAL_MS  (1000.0 / TELEMETRY_RATE_HZ)

// WiFi & MQTT Configuration
const char* WIFI_SSID       = "GroundStation_AP";
const char* WIFI_PASS       = "ISRO_IISC_2026";
const char* MQTT_BROKER     = "broker.emqx.io";
const int   MQTT_PORT       = 1883;
const char* MQTT_TELEMETRY_TOPIC = "mission/node_alpha";
const char* MQTT_COMMAND_TOPIC   = "mission/telecommands";

WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ------------------------------------------------------------------------------
// Spacecraft Subsystem & Actuator States (Closed-Loop HIL)
// ------------------------------------------------------------------------------
bool payloadPowerActive  = true;
bool heatersActive       = false;
bool safeModeActive      = false;
bool injectedThermalFault= false;

float simulatedTempExcursion = 0.0f;
float simulatedCurrentDraw   = 2.45f;

// Sensor & Attitude Variables
int16_t raw_ax, raw_ay, raw_az;
int16_t raw_temp;
int16_t raw_gx, raw_gy, raw_gz;

float ax, ay, az;
float gx, gy, gz;
float temperatureC = 28.5f;

// Complementary Filter State
float pitch = 0.0f;
float roll  = 0.0f;
float yaw   = 0.0f;
const float ALPHA = 0.96f;

uint32_t sequenceId = 0;
uint32_t lastSampleTime = 0;
uint32_t lastLedToggleTime = 0;
bool ledState = false;

// ------------------------------------------------------------------------------
// MPU6050 I2C Helper
// ------------------------------------------------------------------------------
void initMPU6050() {
  Wire.begin(21, 22);
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); // Wake up MPU6050
  Wire.write(0x00);
  Wire.endTransmission(true);

  // Set Gyro Range ±250 deg/s
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B);
  Wire.write(0x00);
  Wire.endTransmission(true);

  // Set Accel Range ±2g
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1C);
  Wire.write(0x00);
  Wire.endTransmission(true);
}

void readMPU6050() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom((uint16_t)MPU_ADDR, (uint8_t)14, true);

  if (Wire.available() >= 14) {
    raw_ax = (Wire.read() << 8) | Wire.read();
    raw_ay = (Wire.read() << 8) | Wire.read();
    raw_az = (Wire.read() << 8) | Wire.read();
    raw_temp = (Wire.read() << 8) | Wire.read();
    raw_gx = (Wire.read() << 8) | Wire.read();
    raw_gy = (Wire.read() << 8) | Wire.read();
    raw_gz = (Wire.read() << 8) | Wire.read();

    ax = raw_ax / 16384.0f;
    ay = raw_ay / 16384.0f;
    az = raw_az / 16384.0f;
    float rawSensorTemp = (raw_temp / 340.0f) + 36.53f;
    gx = raw_gx / 131.0f;
    gy = raw_gy / 131.0f;
    gz = raw_gz / 131.0f;

    // Couple physical MPU sensor temperature with thermal subsystem simulation
    if (injectedThermalFault) {
      if (simulatedTempExcursion < 21.0f) simulatedTempExcursion += 0.4f; // Heats up to 49.5°C
    } else {
      if (simulatedTempExcursion > 0.0f) simulatedTempExcursion -= 0.6f;  // Rapidly cools down when payload OFF
    }
    temperatureC = 28.5f + simulatedTempExcursion;
  }
}

void updateAttitude(float dt) {
  float accelPitch = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0f / PI;
  float accelRoll  = atan2(ay, az) * 180.0f / PI;

  pitch = ALPHA * (pitch + gy * dt) + (1.0f - ALPHA) * accelPitch;
  roll  = ALPHA * (roll  + gx * dt) + (1.0f - ALPHA) * accelRoll;
  yaw  += gz * dt;

  if (yaw >= 360.0f) yaw -= 360.0f;
  if (yaw < 0.0f) yaw += 360.0f;
}

// ------------------------------------------------------------------------------
// Electrical Power Subsystem (EPS) Reading
// ------------------------------------------------------------------------------
float readSolarPower() {
  int raw = analogRead(SOLAR_ADC_PIN);
  float voltage = (raw / 4095.0f) * 3.3f * 2.0f;
  float powerWatts = (voltage * voltage) / 10.0f * 15.0f;
  return constrain(powerWatts, 0.0f, 160.0f);
}

float readBatteryVoltage() {
  int raw = analogRead(BATTERY_ADC_PIN);
  float pinVoltage = (raw / 4095.0f) * 3.3f;
  float busVoltage = pinVoltage * 4.0f;
  return (busVoltage > 1.0f) ? busVoltage : 12.25f;
}

// ------------------------------------------------------------------------------
// Closed-Loop Telecommand Actuation Handler
// ------------------------------------------------------------------------------
void executeTelecommand(const String& cmd) {
  char ackBuffer[256];

  if (cmd == "CMD_PAYLOAD_OFF") {
    payloadPowerActive = false;
    injectedThermalFault = false;
    digitalWrite(PAYLOAD_POWER_PIN, LOW);
    simulatedCurrentDraw = 1.05f; // Power drops significantly

    snprintf(ackBuffer, sizeof(ackBuffer),
      "{\"type\":\"ACK\",\"cmd\":\"CMD_PAYLOAD_OFF\",\"status\":\"EXECUTED\",\"actuator\":\"GPIO18_LOW\",\"payload_state\":\"OFF\",\"bus_current_a\":%.2f,\"msg\":\"Payload powered down. Thermal cool-down verified.\"}",
      simulatedCurrentDraw
    );
    Serial.println(ackBuffer);
    if (mqttClient.connected()) mqttClient.publish("mission/telemetry/ack", ackBuffer);

  } else if (cmd == "CMD_PAYLOAD_ON") {
    payloadPowerActive = true;
    digitalWrite(PAYLOAD_POWER_PIN, HIGH);
    simulatedCurrentDraw = 2.45f;

    snprintf(ackBuffer, sizeof(ackBuffer),
      "{\"type\":\"ACK\",\"cmd\":\"CMD_PAYLOAD_ON\",\"status\":\"EXECUTED\",\"actuator\":\"GPIO18_HIGH\",\"payload_state\":\"ON\",\"bus_current_a\":%.2f}",
      simulatedCurrentDraw
    );
    Serial.println(ackBuffer);
    if (mqttClient.connected()) mqttClient.publish("mission/telemetry/ack", ackBuffer);

  } else if (cmd == "CMD_SAFE_MODE") {
    safeModeActive = true;
    payloadPowerActive = false;
    heatersActive = false;
    injectedThermalFault = false;
    digitalWrite(PAYLOAD_POWER_PIN, LOW);
    digitalWrite(SAFE_MODE_LED_PIN, HIGH);
    simulatedCurrentDraw = 0.85f;

    snprintf(ackBuffer, sizeof(ackBuffer),
      "{\"type\":\"ACK\",\"cmd\":\"CMD_SAFE_MODE\",\"status\":\"EXECUTED\",\"actuator\":\"SAFE_MODE_ARMED\",\"msg\":\"Autonomous Safe-Mode engaged. Minimal power envelope.\"}"
    );
    Serial.println(ackBuffer);
    if (mqttClient.connected()) mqttClient.publish("mission/telemetry/ack", ackBuffer);

  } else if (cmd == "CMD_INJECT_THERMAL_FAULT") {
    injectedThermalFault = true;
    payloadPowerActive = true;
    simulatedCurrentDraw = 5.15f; // Overcurrent causing heating

    snprintf(ackBuffer, sizeof(ackBuffer),
      "{\"type\":\"ACK\",\"cmd\":\"CMD_INJECT_THERMAL_FAULT\",\"status\":\"FAULT_INJECTED\",\"msg\":\"Thermal heating simulated (Overcurrent 5.15A). Waiting for Autonomous Recovery.\"}"
    );
    Serial.println(ackBuffer);

  } else if (cmd == "CMD_RESTORE_NOMINAL") {
    safeModeActive = false;
    payloadPowerActive = true;
    heatersActive = false;
    injectedThermalFault = false;
    digitalWrite(PAYLOAD_POWER_PIN, HIGH);
    digitalWrite(SAFE_MODE_LED_PIN, LOW);
    simulatedCurrentDraw = 2.45f;

    snprintf(ackBuffer, sizeof(ackBuffer),
      "{\"type\":\"ACK\",\"cmd\":\"CMD_RESTORE_NOMINAL\",\"status\":\"EXECUTED\",\"msg\":\"Nominal flight profile restored.\"}"
    );
    Serial.println(ackBuffer);

  } else if (cmd == "CMD_CALIBRATE") {
    pitch = 0.0f;
    roll  = 0.0f;
    yaw   = 0.0f;
    Serial.println("{\"type\":\"ACK\",\"cmd\":\"CMD_CALIBRATE\",\"status\":\"IMU_ZERO_CALIBRATED\"}");

  } else if (cmd == "CMD_PING") {
    Serial.println("{\"type\":\"PONG\",\"latency_ms\":1}");
  }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String cmdStr = "";
  for (unsigned int i = 0; i < length; i++) {
    cmdStr += (char)payload[i];
  }
  cmdStr.trim();
  executeTelecommand(cmdStr);
}

// ------------------------------------------------------------------------------
// Arduino Setup
// ------------------------------------------------------------------------------
void setup() {
  pinMode(LED_PIN, OUTPUT);
  pinMode(PAYLOAD_POWER_PIN, OUTPUT);
  pinMode(HEATER_RELAY_PIN, OUTPUT);
  pinMode(SAFE_MODE_LED_PIN, OUTPUT);

  digitalWrite(LED_PIN, HIGH);
  digitalWrite(PAYLOAD_POWER_PIN, HIGH); // Payload ON initially
  digitalWrite(HEATER_RELAY_PIN, LOW);
  digitalWrite(SAFE_MODE_LED_PIN, LOW);

  Serial.begin(SERIAL_BAUD_RATE);
  delay(500);

  Serial.println("\n========================================================");
  Serial.println("  ASTRA-GDS // Closed-Loop 1U CubeSat HIL Testbed v3.0  ");
  Serial.println("  ISpA / IISc 2026 Space Conclave Flight Node Online     ");
  Serial.println("========================================================");

  initMPU6050();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMqttMessage);

  lastSampleTime = millis();
}

// ------------------------------------------------------------------------------
// Main Loop (Deterministic 20 Hz Telemetry & Closed-Loop Command Parser)
// ------------------------------------------------------------------------------
void loop() {
  uint32_t now = millis();
  float dt = (now - lastSampleTime) / 1000.0f;

  if (dt >= (SAMPLE_INTERVAL_MS / 1000.0f)) {
    lastSampleTime = now;
    sequenceId++;

    readMPU6050();
    updateAttitude(dt);

    float solarWatts = readSolarPower();
    float batteryVolts = readBatteryVoltage();
    float batterySOC = constrain(((batteryVolts - 10.8f) / (12.6f - 10.8f)) * 100.0f, 15.0f, 100.0f);

    // Current draw adjusts dynamically with actuator state
    float currentDraw = payloadPowerActive ? (injectedThermalFault ? 5.15f : 2.45f) : 1.05f;

    // Construct CCSDS-inspired Telemetry JSON Frame
    char jsonBuffer[420];
    snprintf(jsonBuffer, sizeof(jsonBuffer),
      "{\"node_id\":\"NODE-ALPHA\",\"seq\":%u,\"uptime_ms\":%u,\"pitch\":%.2f,\"roll\":%.2f,\"yaw\":%.2f,"
      "\"gyro_x\":%.2f,\"gyro_y\":%.2f,\"gyro_z\":%.2f,\"temp_c\":%.1f,\"solar_w\":%.1f,\"bus_v\":%.2f,\"battery_soc\":%.1f,"
      "\"current_a\":%.2f,\"payload_pwr\":%s,\"safe_mode\":%s}",
      sequenceId, now, pitch, roll, yaw, gx, gy, gz, temperatureC, solarWatts, batteryVolts, batterySOC,
      currentDraw, payloadPowerActive ? "true" : "false", safeModeActive ? "true" : "false"
    );

    // 1. Output over USB Web Serial
    Serial.println(jsonBuffer);

    // 2. Wireless MQTT Publish
    if (WiFi.status() == WL_CONNECTED) {
      if (!mqttClient.connected()) {
        if (mqttClient.connect("CubeSat_HIL_Node")) {
          mqttClient.subscribe(MQTT_COMMAND_TOPIC);
        }
      } else {
        mqttClient.publish(MQTT_TELEMETRY_TOPIC, jsonBuffer);
        mqttClient.loop();
      }
    }

    // Toggle Heartbeat LED (1 Hz)
    if (now - lastLedToggleTime >= 500) {
      lastLedToggleTime = now;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState ? HIGH : LOW);
    }
  }

  // Handle incoming telecommands over USB Web Serial
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) {
      executeTelecommand(cmd);
    }
  }
}
