/*
 * STM32 HAL reference for Automatically-adjust-PID-parameters serial protocol
 *
 * 作用：
 * 1. 周期性通过串口上报当前控制环数据
 * 2. 接收 PC 端发送的新 PID 参数
 * 3. 应用参数后返回 ACK
 *
 * 你需要根据自己的工程替换：
 * 1. UART 句柄
 * 2. 目标值获取函数
 * 3. 实际值获取函数
 * 4. 控制器计算位置
 */

#include "main.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

#define PID_TUNER_UART_HANDLE       huart1
#define PID_TUNER_UART_TX_GPIO_PORT GPIOA
#define PID_TUNER_UART_TX_PIN       GPIO_PIN_9
#define PID_TUNER_UART_RX_GPIO_PORT GPIOA
#define PID_TUNER_UART_RX_PIN       GPIO_PIN_10
#define PID_TUNER_LOOP_NAME         "speed"

#define RX_BUFFER_SIZE 128
#define TX_BUFFER_SIZE 128

#define SPEED_KP_MIN 0.01f
#define SPEED_KP_MAX 50.00f
#define SPEED_KI_MIN 0.00f
#define SPEED_KI_MAX 20.00f
#define SPEED_KD_MIN 0.00f
#define SPEED_KD_MAX 10.00f

typedef struct
{
    float kp;
    float ki;
    float kd;
    float integral;
    float prev_error;
    float output;
} PID_Controller_t;

static PID_Controller_t g_speed_pid = {
    .kp = 1.0f,
    .ki = 0.1f,
    .kd = 0.05f,
    .integral = 0.0f,
    .prev_error = 0.0f,
    .output = 0.0f
};

static uint8_t g_rx_byte = 0;
static char g_rx_line[RX_BUFFER_SIZE];
static uint16_t g_rx_index = 0;

static void PIDTuner_StartReceiveIT(void);
static void PIDTuner_ProcessLine(const char *line);
static void PIDTuner_SendInfo(const char *message);
static void PIDTuner_SendAck(const char *loop_name, float kp, float ki, float kd);
static void PIDTuner_SendData(const char *loop_name,
                              float timestamp_s,
                              float target,
                              float actual,
                              float error,
                              float output);
static uint8_t PIDTuner_ApplyCommand(const char *loop_name, float kp, float ki, float kd);
static float PIDTuner_Clamp(float value, float min_value, float max_value);

/*
 * 这里替换成你自己的目标值获取逻辑
 */
static float App_GetSpeedTarget(void)
{
    return 100.0f;
}

/*
 * 这里替换成你自己的实际值获取逻辑
 */
static float App_GetSpeedActual(void)
{
    return 95.0f;
}

/*
 * 这是一个最简 PID 示例。
 * 如果你已经有自己的控制器，可以直接替换这部分。
 */
static float App_ComputeSpeedOutput(PID_Controller_t *pid, float target, float actual, float dt_s)
{
    float error = target - actual;
    float derivative = 0.0f;

    pid->integral += error * dt_s;

    if (dt_s > 1e-6f)
    {
        derivative = (error - pid->prev_error) / dt_s;
    }

    pid->output = pid->kp * error + pid->ki * pid->integral + pid->kd * derivative;
    pid->prev_error = error;

    return pid->output;
}

/*
 * 在初始化时调用一次
 */
void PIDTuner_Init(void)
{
    PIDTuner_StartReceiveIT();
    PIDTuner_SendInfo("STM32 tuner bridge ready");
}

/*
 * 在固定周期任务中调用。
 * 例如：
 * 1. 定时器中断
 * 2. RTOS 周期任务
 * 3. 主循环固定周期调度
 */
void PIDTuner_Task(float dt_s)
{
    float timestamp_s = HAL_GetTick() / 1000.0f;
    float target = App_GetSpeedTarget();
    float actual = App_GetSpeedActual();
    float output = App_ComputeSpeedOutput(&g_speed_pid, target, actual, dt_s);
    float error = target - actual;

    PIDTuner_SendData(PID_TUNER_LOOP_NAME, timestamp_s, target, actual, error, output);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance != PID_TUNER_UART_HANDLE.Instance)
    {
        return;
    }

    if (g_rx_byte == '\n' || g_rx_byte == '\r')
    {
        if (g_rx_index > 0)
        {
            g_rx_line[g_rx_index] = '\0';
            PIDTuner_ProcessLine(g_rx_line);
            g_rx_index = 0;
        }
    }
    else
    {
        if (g_rx_index < (RX_BUFFER_SIZE - 1))
        {
            g_rx_line[g_rx_index++] = (char)g_rx_byte;
        }
        else
        {
            g_rx_index = 0;
            PIDTuner_SendInfo("RX line too long");
        }
    }

    PIDTuner_StartReceiveIT();
}

static void PIDTuner_StartReceiveIT(void)
{
    HAL_UART_Receive_IT(&PID_TUNER_UART_HANDLE, &g_rx_byte, 1);
}

static void PIDTuner_ProcessLine(const char *line)
{
    char loop_name[16];
    float kp = 0.0f;
    float ki = 0.0f;
    float kd = 0.0f;

    if (strncmp(line, "PID:", 4) != 0)
    {
        PIDTuner_SendInfo("Ignored non-PID line");
        return;
    }

    if (sscanf(line, "PID:%15[^:]:%f,%f,%f", loop_name, &kp, &ki, &kd) != 4)
    {
        PIDTuner_SendInfo("PID parse failed");
        return;
    }

    if (PIDTuner_ApplyCommand(loop_name, kp, ki, kd))
    {
        PIDTuner_SendAck(loop_name, kp, ki, kd);
    }
}

static uint8_t PIDTuner_ApplyCommand(const char *loop_name, float kp, float ki, float kd)
{
    if (strcmp(loop_name, PID_TUNER_LOOP_NAME) != 0)
    {
        PIDTuner_SendInfo("Unknown loop");
        return 0;
    }

    if (!isfinite(kp) || !isfinite(ki) || !isfinite(kd))
    {
        PIDTuner_SendInfo("Invalid PID value");
        return 0;
    }

    kp = PIDTuner_Clamp(kp, SPEED_KP_MIN, SPEED_KP_MAX);
    ki = PIDTuner_Clamp(ki, SPEED_KI_MIN, SPEED_KI_MAX);
    kd = PIDTuner_Clamp(kd, SPEED_KD_MIN, SPEED_KD_MAX);

    g_speed_pid.kp = kp;
    g_speed_pid.ki = ki;
    g_speed_pid.kd = kd;

    PIDTuner_SendInfo("Speed PID updated");
    return 1;
}

static void PIDTuner_SendData(const char *loop_name,
                              float timestamp_s,
                              float target,
                              float actual,
                              float error,
                              float output)
{
    char tx_buffer[TX_BUFFER_SIZE];
    int len = snprintf(tx_buffer,
                       sizeof(tx_buffer),
                       "DATA:%s:%.4f,%.4f,%.4f,%.4f,%.4f\n",
                       loop_name,
                       timestamp_s,
                       target,
                       actual,
                       error,
                       output);

    if (len > 0)
    {
        HAL_UART_Transmit(&PID_TUNER_UART_HANDLE, (uint8_t *)tx_buffer, (uint16_t)len, 100);
    }
}

static void PIDTuner_SendAck(const char *loop_name, float kp, float ki, float kd)
{
    char tx_buffer[TX_BUFFER_SIZE];
    int len = snprintf(tx_buffer,
                       sizeof(tx_buffer),
                       "ACK:%s:%.6f,%.6f,%.6f\n",
                       loop_name,
                       kp,
                       ki,
                       kd);

    if (len > 0)
    {
        HAL_UART_Transmit(&PID_TUNER_UART_HANDLE, (uint8_t *)tx_buffer, (uint16_t)len, 100);
    }
}

static void PIDTuner_SendInfo(const char *message)
{
    char tx_buffer[TX_BUFFER_SIZE];
    int len = snprintf(tx_buffer, sizeof(tx_buffer), "INFO:%s\n", message);

    if (len > 0)
    {
        HAL_UART_Transmit(&PID_TUNER_UART_HANDLE, (uint8_t *)tx_buffer, (uint16_t)len, 100);
    }
}

static float PIDTuner_Clamp(float value, float min_value, float max_value)
{
    if (value < min_value)
    {
        return min_value;
    }

    if (value > max_value)
    {
        return max_value;
    }

    return value;
}
