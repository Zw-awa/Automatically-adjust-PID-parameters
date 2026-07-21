#include "pid_tuner_port.h"

#include "pid_tuner_config.h"
#include "usart.h"

#include <string.h>

/* 本文件是 HAL 适配层：只负责 UART IT 收发、HAL Tick 和收发缓冲区。 */
static uint8_t g_rx_byte;
static char g_rx_build[PID_TUNER_RX_SIZE];
static char g_rx_line[PID_TUNER_RX_SIZE];
static volatile uint16_t g_rx_index;
static volatile uint8_t g_line_ready;
static volatile uint8_t g_rx_overflow;

static char g_tx_ring[PID_TUNER_TX_SIZE];
static uint8_t g_tx_byte;
static volatile uint16_t g_tx_head;
static volatile uint16_t g_tx_tail;
static volatile uint8_t g_tx_busy;

static uint16_t tx_free(void)
{
    uint16_t head = g_tx_head;
    uint16_t tail = g_tx_tail;
    if (head >= tail)
    {
        return (uint16_t)(PID_TUNER_TX_SIZE - (head - tail) - 1U);
    }
    return (uint16_t)(tail - head - 1U);
}

static void start_tx(void)
{
    if (g_tx_busy || g_tx_tail == g_tx_head) return;
    g_tx_byte = (uint8_t)g_tx_ring[g_tx_tail];
    g_tx_busy = 1U;
    if (HAL_UART_Transmit_IT(&huart1, &g_tx_byte, 1U) != HAL_OK)
    {
        g_tx_busy = 0U;
    }
}

uint8_t PIDTuner_PortInit(void)
{
    if (huart1.Instance != USART1) return 0U;
    /* CubeMX 已完成时钟、GPIO、USART 和 NVIC；这里只启动 IT 接收。 */
    return HAL_UART_Receive_IT(&huart1, &g_rx_byte, 1U) == HAL_OK;
}

void PIDTuner_PortPoll(void)
{
    start_tx();
}

uint32_t PIDTuner_PortMillis(void)
{
    return HAL_GetTick();
}

uint8_t PIDTuner_PortWrite(const char *text)
{
    uint16_t length = (uint16_t)strlen(text);
    uint16_t index;

    __disable_irq();
    if (length > tx_free())
    {
        __enable_irq();
        return 0U;
    }
    for (index = 0U; index < length; ++index)
    {
        g_tx_ring[g_tx_head] = text[index];
        g_tx_head = (uint16_t)((g_tx_head + 1U) % PID_TUNER_TX_SIZE);
    }
    __enable_irq();
    start_tx();
    return 1U;
}

PIDTuner_PortLineStatus PIDTuner_PortReadLine(char *line, uint16_t size)
{
    PIDTuner_PortLineStatus status = PID_TUNER_PORT_LINE_NONE;

    if (line == 0 || size == 0U) return status;
    __disable_irq();
    if (g_rx_overflow)
    {
        g_rx_overflow = 0U;
        status = PID_TUNER_PORT_LINE_OVERFLOW;
    }
    else if (g_line_ready)
    {
        (void)strncpy(line, g_rx_line, size);
        line[size - 1U] = '\0';
        g_line_ready = 0U;
        status = PID_TUNER_PORT_LINE_READY;
    }
    __enable_irq();
    return status;
}

void PIDTuner_PortOnRxComplete(void)
{
    if (g_rx_byte == '\n' || g_rx_byte == '\r')
    {
        if (g_rx_index > 0U && !g_line_ready)
        {
            g_rx_build[g_rx_index] = '\0';
            (void)memcpy(g_rx_line, g_rx_build, g_rx_index + 1U);
            g_line_ready = 1U;
        }
        g_rx_index = 0U;
    }
    else if (g_rx_index < PID_TUNER_RX_SIZE - 1U)
    {
        g_rx_build[g_rx_index++] = (char)g_rx_byte;
    }
    else
    {
        g_rx_index = 0U;
        g_rx_overflow = 1U;
    }
    (void)HAL_UART_Receive_IT(&huart1, &g_rx_byte, 1U);
}

void PIDTuner_PortOnTxComplete(void)
{
    if (g_tx_tail != g_tx_head)
    {
        g_tx_tail = (uint16_t)((g_tx_tail + 1U) % PID_TUNER_TX_SIZE);
    }
    g_tx_busy = 0U;
    start_tx();
}

void PIDTuner_PortOnError(void)
{
    g_tx_busy = 0U;
    (void)HAL_UART_Receive_IT(&huart1, &g_rx_byte, 1U);
}
