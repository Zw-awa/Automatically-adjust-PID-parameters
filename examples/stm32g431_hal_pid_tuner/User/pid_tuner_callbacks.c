#include "pid_tuner_port.h"

#include "usart.h"

/*
 * 如果自己的工程已经实现了这些 HAL 回调，不要复制本文件；
 * 只需在原回调中调用 PIDTuner_PortOn...()。
 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) PIDTuner_PortOnRxComplete();
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) PIDTuner_PortOnTxComplete();
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) PIDTuner_PortOnError();
}
