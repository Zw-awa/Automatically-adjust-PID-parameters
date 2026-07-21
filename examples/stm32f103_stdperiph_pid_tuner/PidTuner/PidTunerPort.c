#include "PidTunerPort.h"

#include "PidTunerConfig.h"
#include "stm32f10x.h"

#include <string.h>

/* 本文件是标准库适配层：只负责 USART1、1 ms 时基和收发缓冲区。 */
static volatile uint32_t g_tick_ms;
static char g_rx_build[PID_TUNER_RX_SIZE];
static char g_rx_line[PID_TUNER_RX_SIZE];
static volatile uint16_t g_rx_index;
static volatile uint8_t g_line_ready;
static volatile uint8_t g_rx_overflow;

static char g_tx_ring[PID_TUNER_TX_SIZE];
static volatile uint16_t g_tx_head;
static volatile uint16_t g_tx_tail;

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

static void init_usart1(void)
{
    GPIO_InitTypeDef gpio;
    USART_InitTypeDef usart;
    NVIC_InitTypeDef nvic;

    /* USART1 初始化需要时钟、TX/RX GPIO、外设本体、NVIC 四部分。 */
    RCC_APB2PeriphClockCmd(
        RCC_APB2Periph_GPIOA | RCC_APB2Periph_USART1,
        ENABLE);

    gpio.GPIO_Pin = GPIO_Pin_9;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    GPIO_Init(GPIOA, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_10;
    gpio.GPIO_Mode = GPIO_Mode_IPU;
    GPIO_Init(GPIOA, &gpio);

    USART_StructInit(&usart);
    usart.USART_BaudRate = 115200U;
    usart.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART1, &usart);
    USART_ITConfig(USART1, USART_IT_RXNE, ENABLE);

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);
    nvic.NVIC_IRQChannel = USART1_IRQn;
    nvic.NVIC_IRQChannelPreemptionPriority = 1U;
    nvic.NVIC_IRQChannelSubPriority = 1U;
    nvic.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&nvic);
    USART_Cmd(USART1, ENABLE);
}

uint8_t PIDTuner_PortInit(void)
{
    SystemCoreClockUpdate();
    init_usart1();

    /* 核心需要 1 ms 时间基准；移植到已有 SysTick 时可保留原配置。 */
    if (SysTick_Config(SystemCoreClock / 1000U) != 0U) return 0U;
    return 1U;
}

void PIDTuner_PortPoll(void)
{
    /* 标准库版不需要额外轮询，保留接口以便和 HAL 版结构一致。 */
}

uint32_t PIDTuner_PortMillis(void)
{
    return g_tick_ms;
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
    USART_ITConfig(USART1, USART_IT_TXE, ENABLE);
    __enable_irq();
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

void PIDTuner_PortTick1ms(void)
{
    ++g_tick_ms;
}

void PIDTuner_PortOnUsart1Irq(void)
{
    /* 中断只搬运字节；sscanf、printf 和 PID 都在主循环执行。 */
    if (USART_GetITStatus(USART1, USART_IT_RXNE) != RESET)
    {
        uint8_t byte = (uint8_t)USART_ReceiveData(USART1);
        if (byte == '\n' || byte == '\r')
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
            g_rx_build[g_rx_index++] = (char)byte;
        }
        else
        {
            g_rx_index = 0U;
            g_rx_overflow = 1U;
        }
    }

    if (USART_GetITStatus(USART1, USART_IT_TXE) != RESET)
    {
        if (g_tx_tail != g_tx_head)
        {
            USART_SendData(USART1, (uint8_t)g_tx_ring[g_tx_tail]);
            g_tx_tail = (uint16_t)((g_tx_tail + 1U) % PID_TUNER_TX_SIZE);
        }
        else
        {
            USART_ITConfig(USART1, USART_IT_TXE, DISABLE);
        }
    }
}
