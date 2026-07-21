#include "pid_tuner.h"

#include "pid_tuner_config.h"
#include "pid_tuner_port.h"
#include "pid_tuner_user.h"

#include <float.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/*
 * 本文件只做四件事：解析协议、管理参数切换、执行 PID、发送遥测。
 * HAL UART/回调在 pid_tuner_port.c，传感器/PWM 在 pid_tuner_user.c。
 * 一般移植时不需要修改本文件。
 */
typedef struct
{
    float kp;
    float ki;
    float kd;
    float integral;
    float previous_measurement;
    float derivative_state;
    float output;
    uint8_t initialized;
} PID_Controller;

typedef struct
{
    float kp;
    float ki;
    float kd;
    uint32_t received_ms;
    char request_id[PID_TUNER_REQUEST_ID_SIZE];
    uint8_t ready;
} PID_Update;

static PID_Controller g_pid = {
    PID_TUNER_INITIAL_KP,
    PID_TUNER_INITIAL_KI,
    PID_TUNER_INITIAL_KD,
    0.0f, 0.0f, 0.0f, 0.0f, 0U
};
static PID_Update g_pending;
static PID_Update g_applied;
static float g_last_target;
static float g_last_actual;
static uint8_t g_ready;
static uint8_t g_input_fault_reported;

static float clampf(float value, float minimum, float maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

static uint8_t finitef(float value)
{
    return (value == value && value <= FLT_MAX && value >= -FLT_MAX) ? 1U : 0U;
}

static uint8_t pid_in_range(float kp, float ki, float kd)
{
    return finitef(kp) && finitef(ki) && finitef(kd)
        && kp >= PID_TUNER_KP_MIN && kp <= PID_TUNER_KP_MAX
        && ki >= PID_TUNER_KI_MIN && ki <= PID_TUNER_KI_MAX
        && kd >= PID_TUNER_KD_MIN && kd <= PID_TUNER_KD_MAX;
}

static uint8_t config_is_valid(void)
{
    return PID_TUNER_CONTROL_PERIOD_MS > 0U
        && PID_TUNER_TELEMETRY_PERIOD_MS >= PID_TUNER_CONTROL_PERIOD_MS
        && PID_TUNER_OUTPUT_MIN < PID_TUNER_OUTPUT_MAX
        && PID_TUNER_RX_SIZE >= 32U
        && PID_TUNER_TX_SIZE >= 128U
        && strlen(PID_TUNER_LOOP_NAME) > 0U
        && strlen(PID_TUNER_LOOP_NAME) < 16U
        && pid_in_range(
            PID_TUNER_INITIAL_KP,
            PID_TUNER_INITIAL_KI,
            PID_TUNER_INITIAL_KD);
}

static uint8_t queue_format(const char *format, ...)
{
    char line[PID_TUNER_FORMAT_LINE_SIZE];
    int length;
    va_list args;

    va_start(args, format);
    length = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (length <= 0 || length >= (int)sizeof(line)) return 0U;
    return PIDTuner_PortWrite(line);
}

static void send_nack(const char *request_id, const char *reason)
{
    (void)queue_format(
        "NACK:%s:%s:%s\n",
        request_id,
        PID_TUNER_LOOP_NAME,
        reason);
}

static void parse_command(const char *line)
{
    char request_id[PID_TUNER_REQUEST_ID_SIZE] = {0};
    char loop_name[16] = {0};
    float kp;
    float ki;
    float kd;
    char trailing;

    if (sscanf(
            line,
            "PID:%12[A-Za-z0-9_.-]:%15[A-Za-z0-9_.-]:%f,%f,%f%c",
            request_id,
            loop_name,
            &kp,
            &ki,
            &kd,
            &trailing) != 5)
    {
        send_nack("unknown", "BAD_FORMAT");
        return;
    }
    if (strcmp(loop_name, PID_TUNER_LOOP_NAME) != 0)
    {
        send_nack(request_id, "UNKNOWN_LOOP");
        return;
    }
    if (!pid_in_range(kp, ki, kd))
    {
        send_nack(request_id, "OUT_OF_RANGE");
        return;
    }
    if (g_pending.ready)
    {
        send_nack(request_id, "BUSY");
        return;
    }

    g_pending.kp = kp;
    g_pending.ki = ki;
    g_pending.kd = kd;
    g_pending.received_ms = PIDTuner_PortMillis();
    (void)strncpy(
        g_pending.request_id,
        request_id,
        PID_TUNER_REQUEST_ID_SIZE - 1U);
    g_pending.ready = 1U;
}

static void apply_pending_update(float error)
{
    float previous_output;

    if (!g_pending.ready) return;
    if ((uint32_t)(PIDTuner_PortMillis() - g_pending.received_ms)
        > PID_TUNER_UPDATE_MAX_AGE_MS)
    {
        send_nack(g_pending.request_id, "EXPIRED");
        g_pending.ready = 0U;
        return;
    }

    previous_output = g_pid.output;
    g_pid.kp = g_pending.kp;
    g_pid.ki = g_pending.ki;
    g_pid.kd = g_pending.kd;
    g_pid.derivative_state = 0.0f;
    if (g_pid.ki > 1e-6f)
    {
        g_pid.integral = clampf(
            (previous_output - g_pid.kp * error) / g_pid.ki,
            PID_TUNER_OUTPUT_MIN / g_pid.ki,
            PID_TUNER_OUTPUT_MAX / g_pid.ki);
    }
    else
    {
        g_pid.integral = 0.0f;
    }
    g_pid.initialized = 0U;

    g_applied.kp = g_pid.kp;
    g_applied.ki = g_pid.ki;
    g_applied.kd = g_pid.kd;
    (void)strncpy(
        g_applied.request_id,
        g_pending.request_id,
        PID_TUNER_REQUEST_ID_SIZE - 1U);
    g_applied.ready = 1U;
    g_pending.ready = 0U;
}

static void control_step(void)
{
    const float dt = PID_TUNER_CONTROL_PERIOD_MS / 1000.0f;
    float target = PIDTuner_UserReadTarget();
    float actual = PIDTuner_UserReadActual();
    float error;
    float raw_derivative = 0.0f;
    float derivative_alpha;
    float candidate_integral;
    float unsaturated;

    if (!finitef(target) || !finitef(actual))
    {
        PIDTuner_UserWriteOutput(0.0f, dt);
        if (!g_input_fault_reported)
        {
            (void)PIDTuner_PortWrite("INFO:FAULT:INVALID_TARGET_OR_ACTUAL\n");
            g_input_fault_reported = 1U;
        }
        return;
    }
    g_input_fault_reported = 0U;
    g_last_target = target;
    g_last_actual = actual;
    error = target - actual;

    apply_pending_update(error);
    if (g_pid.initialized)
    {
        raw_derivative = -(actual - g_pid.previous_measurement) / dt;
        derivative_alpha = PID_TUNER_D_FILTER_TAU_S
            / (PID_TUNER_D_FILTER_TAU_S + dt);
        g_pid.derivative_state = derivative_alpha * g_pid.derivative_state
            + (1.0f - derivative_alpha) * raw_derivative;
    }

    candidate_integral = g_pid.integral + error * dt;
    unsaturated = g_pid.kp * error
        + g_pid.ki * candidate_integral
        + g_pid.kd * g_pid.derivative_state;
    if ((unsaturated < PID_TUNER_OUTPUT_MAX
            && unsaturated > PID_TUNER_OUTPUT_MIN)
        || (unsaturated >= PID_TUNER_OUTPUT_MAX && error < 0.0f)
        || (unsaturated <= PID_TUNER_OUTPUT_MIN && error > 0.0f))
    {
        g_pid.integral = candidate_integral;
    }

    g_pid.output = clampf(
        g_pid.kp * error
            + g_pid.ki * g_pid.integral
            + g_pid.kd * g_pid.derivative_state,
        PID_TUNER_OUTPUT_MIN,
        PID_TUNER_OUTPUT_MAX);
    g_pid.previous_measurement = actual;
    g_pid.initialized = 1U;
    PIDTuner_UserWriteOutput(g_pid.output, dt);
}

PIDTuner_Status PIDTuner_Init(void)
{
    if (!config_is_valid()) return PID_TUNER_ERROR_CONFIG;
    if (!PIDTuner_PortInit()) return PID_TUNER_ERROR_PORT;

    g_ready = 1U;
    (void)queue_format(
        "INFO:READY:%s:control=%ums,telemetry=%ums,demo=%u\n",
        PID_TUNER_LOOP_NAME,
        PID_TUNER_CONTROL_PERIOD_MS,
        PID_TUNER_TELEMETRY_PERIOD_MS,
        PID_TUNER_USE_SOFTWARE_PLANT);
    return PID_TUNER_OK;
}

void PIDTuner_Poll(void)
{
    static uint32_t last_control_ms;
    static uint32_t last_telemetry_ms;
    char line[PID_TUNER_RX_SIZE];
    uint32_t now;
    PIDTuner_PortLineStatus line_status;

    if (!g_ready) return;
    PIDTuner_PortPoll();
    now = PIDTuner_PortMillis();

    line_status = PIDTuner_PortReadLine(line, sizeof(line));
    if (line_status == PID_TUNER_PORT_LINE_OVERFLOW)
    {
        send_nack("unknown", "LINE_TOO_LONG");
    }
    else if (line_status == PID_TUNER_PORT_LINE_READY)
    {
        parse_command(line);
    }

    if ((uint32_t)(now - last_control_ms) >= PID_TUNER_CONTROL_PERIOD_MS)
    {
        last_control_ms = now;
        control_step();
    }
    if (g_applied.ready)
    {
        if (queue_format(
                "ACK:%s:%s:%.6f,%.6f,%.6f\n",
                g_applied.request_id,
                PID_TUNER_LOOP_NAME,
                g_applied.kp,
                g_applied.ki,
                g_applied.kd))
        {
            g_applied.ready = 0U;
        }
    }
    if ((uint32_t)(now - last_telemetry_ms) >= PID_TUNER_TELEMETRY_PERIOD_MS)
    {
        last_telemetry_ms = now;
        (void)queue_format(
            "DATA:%s:%.3f,%.3f,%.3f,%.3f,%.3f\n",
            PID_TUNER_LOOP_NAME,
            now / 1000.0f,
            g_last_target,
            g_last_actual,
            g_last_target - g_last_actual,
            g_pid.output);
    }
}
