#include "main.h"
#include "usart.h"
#include "pid_tuner.h"

void SystemClock_Config(void);

int main(void)
{
    PIDTuner_Status status;

    /* 先完成 HAL、时钟和 USART 初始化，再启动调参模块。 */
    HAL_Init();
    SystemClock_Config();
    MX_USART1_UART_Init();
    status = PIDTuner_Init();
    if (status != PID_TUNER_OK)
    {
        Error_Handler();
    }

    while (1)
    {
        /* 协议解析、PID 控制和遥测均在主循环完成。 */
        PIDTuner_Poll();
    }
}

void SystemClock_Config(void)
{
    RCC_OscInitTypeDef oscillator = {0};
    RCC_ClkInitTypeDef clock = {0};

    HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);
    oscillator.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    oscillator.HSEState = RCC_HSE_ON;
    oscillator.PLL.PLLState = RCC_PLL_ON;
    oscillator.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    oscillator.PLL.PLLM = RCC_PLLM_DIV3;
    oscillator.PLL.PLLN = 20;
    oscillator.PLL.PLLP = RCC_PLLP_DIV2;
    oscillator.PLL.PLLQ = RCC_PLLQ_DIV2;
    oscillator.PLL.PLLR = RCC_PLLR_DIV2;
    if (HAL_RCC_OscConfig(&oscillator) != HAL_OK)
    {
        Error_Handler();
    }

    clock.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
        | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clock.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clock.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clock.APB1CLKDivider = RCC_HCLK_DIV1;
    clock.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&clock, FLASH_LATENCY_2) != HAL_OK)
    {
        Error_Handler();
    }
}

void Error_Handler(void)
{
    __disable_irq();
    while (1)
    {
    }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    (void)file;
    (void)line;
}
#endif
