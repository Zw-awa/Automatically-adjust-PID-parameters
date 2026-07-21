# STM32G431 HAL PID 调参示例

芯片：STM32G431RBT6，串口：USART1（PA9 TX、PA10 RX），`115200 8N1`。
工程文件是 `MDK-ARM/PID_Tuner_HAL.uvprojx`，工具链为 CubeMX/HAL + Keil MDK。

## 快速开始

1. 安装 STM32G4 Device Pack、ST-Link 驱动和对应 HAL 工程依赖。
2. 双击 `MDK-ARM/PID_Tuner_HAL.uvprojx`，按 `F7` 编译并下载。
3. 串口助手设置 `115200 8N1`，TX/RX 交叉并共地。
4. 复位后应看到 `INFO:READY:speed` 和连续的 `DATA:speed`。

发送：

```text
PID:req001:speed:1.200000,0.100000,0.050000
```

收到同一 `req001` 的 `ACK` 后，说明 UART 收发、主循环和 PID 参数切换都正常。

## CubeMX 初始化清单

自己的 HAL 工程至少需要：

- USART1 异步模式，115200、8 数据位、1 停止位、无校验、无硬件流控。
- PA9 为 USART1_TX，PA10 为 USART1_RX。
- USART1 global interrupt 已开启。
- `HAL_Init()`、时钟配置和 `MX_USART1_UART_Init()` 在 `PIDTuner_Init()` 之前执行。
- 主循环持续调用 `PIDTuner_Poll()`。

本示例的 `pid_tuner_port.c` 使用 UART 中断和 `HAL_GetTick()`，不需要配置 DMA
通道或调用 `MX_DMA_Init()`，也不要求额外的 PID 定时器。工程仍编译 HAL DMA
驱动，因为这个版本的 HAL UART 头文件依赖 DMA 类型。

## HAL 回调怎么合并

示例提供了 `User/pid_tuner_callbacks.c`。如果自己的工程还没有 UART 回调，
可以直接加入它；如果已经有回调，不要复制第二份函数，只在已有回调中调用：

```c
PIDTuner_PortOnRxComplete();
PIDTuner_PortOnTxComplete();
PIDTuner_PortOnError();
```

USART IRQ 仍然由 CubeMX 生成的 `HAL_UART_IRQHandler(&huart1)` 负责。

## 只需要修改的文件

- `User/pid_tuner_config.h`：周期、初始 PID、输出范围和环名称。
- `User/pid_tuner_user.c`：目标值、实际值、执行器输出。

核心 `User/pid_tuner.c` 和端口 `User/pid_tuner_port.c` 通常不需要修改。
默认的 `PID_TUNER_USE_SOFTWARE_PLANT` 为 `1`，不会驱动 PWM；接真实对象时改为 `0`，
然后实现用户文件中标出的传感器和执行器接口。

`PID_Tuner_HAL.ioc` 仅用于查看原始时钟和引脚配置。不要直接重新生成它，
否则可能覆盖当前入口代码和 UART 回调。

第三方 CMSIS/HAL 文件的许可说明见 `THIRD_PARTY_NOTICE.md`。
