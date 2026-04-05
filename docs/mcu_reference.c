/*
 * PID Auto-Tuner - MCU Side Reference Implementation
 *
 * This is a reference implementation for the serial communication protocol
 * that the MCU (e.g., STM32, Arduino, ESP32) needs to implement.
 *
 * Protocol:
 *   MCU -> PC:  DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>\n
 *   PC -> MCU:  PID:<loop>:<Kp>,<Ki>,<Kd>\n
 *   MCU -> PC:  ACK:<loop>:<Kp>,<Ki>,<Kd>\n
 *   MCU -> PC:  INFO:<message>\n
 *
 * Adapt this code to your specific MCU platform.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

// ─── PID Parameters (modifiable at runtime) ───
typedef struct {
    float kp;
    float ki;
    float kd;
} PID_Params_t;

// Define your control loops here
PID_Params_t speed_pid  = {1.0f, 0.1f, 0.05f};
PID_Params_t steer_pid  = {2.0f, 0.0f, 1.0f};

// ─── Serial Protocol Functions ───

/**
 * Send DATA message to PC
 * Call this in your main control loop at the desired reporting rate
 */
void send_data(const char* loop_name, float timestamp,
               float target, float actual, float error, float output)
{
    // Use your platform's serial print function
    // Arduino: Serial.printf(...)
    // STM32 HAL: sprintf + HAL_UART_Transmit(...)
    printf("DATA:%s:%.4f,%.3f,%.3f,%.4f,%.4f\n",
           loop_name, timestamp, target, actual, error, output);
}

/**
 * Send INFO message to PC
 */
void send_info(const char* message)
{
    printf("INFO:%s\n", message);
}

/**
 * Send ACK message to confirm parameter update
 */
void send_ack(const char* loop_name, PID_Params_t* params)
{
    printf("ACK:%s:%.6f,%.6f,%.6f\n",
           loop_name, params->kp, params->ki, params->kd);
}

/**
 * Parse incoming PID command from PC
 * Format: PID:<loop>:<Kp>,<Ki>,<Kd>\n
 *
 * Returns 1 if valid command parsed, 0 otherwise.
 */
int parse_pid_command(const char* line, char* loop_name, PID_Params_t* params)
{
    // Check prefix
    if (strncmp(line, "PID:", 4) != 0) {
        return 0;
    }

    // Find loop name
    const char* p = line + 4;
    const char* colon = strchr(p, ':');
    if (!colon) return 0;

    int name_len = (int)(colon - p);
    if (name_len <= 0 || name_len > 31) return 0;
    strncpy(loop_name, p, name_len);
    loop_name[name_len] = '\0';

    // Parse Kp, Ki, Kd
    float kp, ki, kd;
    if (sscanf(colon + 1, "%f,%f,%f", &kp, &ki, &kd) != 3) {
        return 0;
    }

    params->kp = kp;
    params->ki = ki;
    params->kd = kd;
    return 1;
}

/**
 * Process a received serial line
 * Call this whenever a complete line is received from PC
 */
void process_serial_line(const char* line)
{
    char loop_name[32];
    PID_Params_t new_params;

    if (!parse_pid_command(line, loop_name, &new_params)) {
        return; // Not a PID command, ignore
    }

    // Safety: clamp parameters to sane limits before applying
    // IMPORTANT: Adjust these limits for your specific application!
    if (new_params.kp < 0.0f)  new_params.kp = 0.0f;
    if (new_params.kp > 100.0f) new_params.kp = 100.0f;
    if (new_params.ki < 0.0f)  new_params.ki = 0.0f;
    if (new_params.ki > 50.0f) new_params.ki = 50.0f;
    if (new_params.kd < 0.0f)  new_params.kd = 0.0f;
    if (new_params.kd > 50.0f) new_params.kd = 50.0f;

    // Apply to the correct loop
    if (strcmp(loop_name, "speed") == 0) {
        speed_pid = new_params;
        send_ack("speed", &speed_pid);
    } else if (strcmp(loop_name, "steering") == 0) {
        steer_pid = new_params;
        send_ack("steering", &steer_pid);
    } else {
        send_info("Unknown loop name");
    }
}

/*
 * ─── Example: Integration into your main loop ───
 *
 * void main_control_loop(void)
 * {
 *     static uint32_t report_counter = 0;
 *
 *     // Your PID control logic here...
 *     float error = target_speed - actual_speed;
 *     float output = pid_calculate(&speed_pid, error);
 *     motor_set_pwm(output);
 *
 *     // Report data every N cycles (e.g., every 10ms)
 *     if (++report_counter % 10 == 0) {
 *         float timestamp = get_time_ms() / 1000.0f;
 *         send_data("speed", timestamp,
 *                   target_speed, actual_speed, error, output);
 *     }
 *
 *     // Check for incoming serial commands
 *     if (serial_available()) {
 *         char line[128];
 *         serial_read_line(line, sizeof(line));
 *         process_serial_line(line);
 *     }
 * }
 */
