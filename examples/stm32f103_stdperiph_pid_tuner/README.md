# STM32F103 标准库 PID 调参示例

芯片：STM32F103C8，串口：USART1（PA9 TX、PA10 RX），`115200 8N1`。
工程文件是 `PID_Tuner_Std.uvprojx`，工具链为 Keil MDK/ARMCC。

## 快速开始

1. 安装 STM32F1 Device Pack 和 ST-Link 驱动。
2. 双击 `PID_Tuner_Std.uvprojx`，按 `F7` 编译并下载。
3. 串口助手设置 `115200 8N1`，TX/RX 交叉并共地。
4. 复位后应看到 `INFO:READY:speed` 和连续的 `DATA:speed`。

发送：

```text
PID:req001:speed:1.200000,0.100000,0.050000
```

收到同一 `req001` 的 `ACK` 后，说明 UART 收发、主循环和 PID 参数切换都正常。

## 初始化顺序

标准库端口文件会初始化 USART1 的 GPIO、外设、NVIC 和 1 ms SysTick。
`main.c` 只需要调用 `PIDTuner_Init()`，然后在 `while (1)` 中持续调用
`PIDTuner_Poll()`。`stm32f10x_it.c` 中的 SysTick 和 USART1 函数只是转发入口。

如果复制到已有工程，不要复制第二个 `SysTick_Handler` 或
`USART1_IRQHandler`，把其中的 `PIDTuner_PortTick1ms()` 和
`PIDTuner_PortOnUsart1Irq()` 合并到原函数即可。

## 只需要修改的文件

- `PidTuner/PidTunerConfig.h`：周期、初始 PID、输出范围和环名称。
- `User/PidTunerUser.c`：目标值、实际值、执行器输出。

核心 `PidTuner/PidTuner.c` 不需要修改。默认的
`PID_TUNER_USE_SOFTWARE_PLANT` 为 `1`，不会驱动 PWM；接真实对象时改为 `0`，
然后实现 `PidTunerUser.c` 中标出的传感器和执行器接口。

第三方标准库文件的许可说明见 `THIRD_PARTY_NOTICE.md`。
