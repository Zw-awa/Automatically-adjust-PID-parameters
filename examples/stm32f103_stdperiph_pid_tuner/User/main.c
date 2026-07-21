#include "stm32f10x.h"
#include "PidTuner.h"

int main(void)
{
    PIDTuner_Status status;

    /* PIDTuner_Init 内依次初始化 USART1、NVIC、1 ms SysTick 和协议状态。 */
    status = PIDTuner_Init();
    if (status != PID_TUNER_OK)
    {
        /* 到这里通常是配置不合法或 SysTick 初始化失败。 */
        while (1)
        {
        }
    }

    while (1)
    {
        /* 所有字符串解析和浮点格式化都在主循环执行，不放进中断。 */
        PIDTuner_Poll();
    }
}
