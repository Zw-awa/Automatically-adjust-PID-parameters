# MCU 集成指南

本指南面向已经使用过 GPIO、定时器、UART 和 Keil/CubeMX，但第一次把一个完整模块
移植进自己工程的用户。

目标不是复制整个示例工程，而是明确：复制哪些文件、初始化什么、修改哪里、如何验证。

## 先跑通完整示例

先从 [STM32 示例总览](../examples/README.md) 选择一套：

- STM32F103C8 标准库版
- STM32G431RBT6 HAL 版

原样编译、下载，用串口助手看到 `INFO:READY` 和连续 `DATA` 后，再移植进自己的工程。
这一步不需要 Python。

## 文件分层

| 层 | 标准库文件 | HAL 文件 | 是否修改 |
| --- | --- | --- | --- |
| 核心 | `PidTuner.c/.h` | `pid_tuner.c/.h` | 通常不改 |
| 配置 | `PidTunerConfig.h` | `pid_tuner_config.h` | 需要检查 |
| 平台端口 | `PidTunerPort.c/.h` | `pid_tuner_port.c/.h` | 换 UART/时基时改 |
| 用户接口 | `PidTunerUser.c/.h` | `pid_tuner_user.c/.h` | 接实机时主要修改 |
| 中断转发 | `stm32f10x_it.c` 中两行 | `pid_tuner_callbacks.c` | 合并到已有函数 |

不要把 ST 的整个 `Library/Drivers` 目录当作 PID 模块复制；使用自己工程已有的固件库。

## 通用初始化顺序

模块依赖三个条件：

1. UART 已配置并能产生接收中断。
2. 有单调递增的 1 ms 时间基准。
3. `PIDTuner_Poll()` 在主循环持续运行。

HAL 典型顺序：

```c
HAL_Init();
SystemClock_Config();
MX_USART1_UART_Init();

if (PIDTuner_Init() != PID_TUNER_OK)
{
    Error_Handler();
}

while (1)
{
    PIDTuner_Poll();
}
```

`PIDTuner_Init()` 必须在 UART 初始化之后调用。只调用一次 `PIDTuner_Poll()` 不会工作。

## 标准库版初始化

示例的 `PidTunerPort.c` 完成：

- GPIOA 和 USART1 外设时钟。
- PA9 复用推挽输出、PA10 上拉输入。
- USART1 `115200 8N1`。
- USART1 RXNE/TXE 中断和 NVIC。
- `SystemCoreClockUpdate()` 与 1 ms SysTick。

如果自己的工程已经配置了 USART1 或 SysTick，应根据现有初始化修改端口文件，避免
重复改变 NVIC 分组或 SysTick 周期。

已有中断函数时不要定义第二份，只合并转发：

```c
void SysTick_Handler(void)
{
    /* 原有 1 ms 逻辑 */
    PIDTuner_PortTick1ms();
}

void USART1_IRQHandler(void)
{
    PIDTuner_PortOnUsart1Irq();
}
```

## HAL/CubeMX 初始化

CubeMX 至少配置：

- USART1 Asynchronous。
- PA9 USART1_TX、PA10 USART1_RX。
- 115200 baud、8 data bits、1 stop bit、no parity、no flow control。
- USART1 global interrupt。
- 正确的系统时钟和 `HAL_IncTick()`。

示例使用 `HAL_UART_Receive_IT` 和 `HAL_UART_Transmit_IT`，不需要配置 UART DMA 通道。
该 HAL 版本的 UART 驱动头文件依赖 DMA 类型，因此工程仍编译 HAL DMA 底层驱动，
但不需要 `MX_DMA_Init()`。

如果工程还没有 HAL UART 回调，可以加入 `pid_tuner_callbacks.c`。如果已经有回调，
不要复制第二份函数，只按 UART 实例转发：

```c
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        PIDTuner_PortOnRxComplete();
    }
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        PIDTuner_PortOnTxComplete();
    }
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        PIDTuner_PortOnError();
    }
}
```

`USART1_IRQHandler()` 中仍需要 CubeMX 生成的：

```c
HAL_UART_IRQHandler(&huart1);
```

## 接入真实控制对象

第一次保持：

```c
#define PID_TUNER_USE_SOFTWARE_PLANT 1U
```

确认 UART、DATA 和 ACK 正常后改为 `0`，然后只实现三个用户函数：

```c
float PIDTuner_UserReadTarget(void)
{
    return Speed_GetTargetRpm();
}

float PIDTuner_UserReadActual(void)
{
    return Encoder_GetSpeedRpm();
}

void PIDTuner_UserWriteOutput(float output, float dt_seconds)
{
    (void)dt_seconds;
    Motor_SetPwm((int16_t)output);
}
```

示例代码不会替你实现真实电机保护。`Motor_SetPwm()` 前后仍需保证方向、死区、限幅、
过流、超速、急停和故障状态正确。

## 配置含义

配置文件中最常修改：

- `PID_TUNER_LOOP_NAME`：必须与 PC 的 `--loop` 和 `config.json` 一致。
- `PID_TUNER_CONTROL_PERIOD_MS`：必须与实际 PID 执行周期一致。
- `PID_TUNER_TELEMETRY_PERIOD_MS`：遥测发送周期，不应小于控制周期。
- 初始 Kp/Ki/Kd：上电参数。
- Kp/Ki/Kd min/max：允许 PC 下发的绝对范围。
- `PID_TUNER_OUTPUT_MIN/MAX`：固件最终输出单位和范围。

PC 配置的 `output_limits` 必须使用相同单位。例如当前软件 demo 使用：

```json
"output_limits": [-100.0, 100.0]
```

真实 PWM 是 `[-1000,1000]`、百分比或电流指令时，应同时修改固件和 PC 配置。

## 协议 v2

每条消息以换行结束。

```text
DATA:<loop>:<timestamp_s>,<target>,<actual>,<error>,<output>
PID:<request_id>:<loop>:<kp>,<ki>,<kd>
ACK:<request_id>:<loop>:<applied_kp>,<applied_ki>,<applied_kd>
NACK:<request_id>:<loop>:<reason>
```

固件必须：

- 在主循环解析字符串，不在 ISR 中执行 `sscanf/printf/PID`。
- 在控制周期边界原子应用参数。
- ACK 返回实际生效值，而不是未经检查的输入。
- 非有限数、越界参数、错误控制环和忙状态返回 NACK。
- 超时命令不能在很久之后突然生效。

PC 只有在 request ID、loop 和参数全部匹配时才确认成功。

## 分阶段实机联调

1. 软件对象：无 PWM，验证 INFO、DATA、PID、ACK/NACK。
2. 只读传感器：输出保持 0，验证 target/actual 和时间戳。
3. 已知稳定参数：接执行器，但不接受远程参数。
4. 手动应用：PC 提建议，人工确认，限制单次变化。
5. 自动化：只有保护、通信超时和回滚全部完成后再考虑。

## 常见故障定位

| 现象 | 优先检查 |
| --- | --- |
| 没有 `INFO:READY` | UART 是否先初始化；`PIDTuner_Init()` 返回值 |
| 有 INFO，没有 DATA | `PIDTuner_Poll()` 是否持续运行；1 ms Tick 是否递增 |
| 有 DATA，没有 ACK | RX 接线、USART 中断、HAL 回调转发 |
| 串口乱码 | 系统时钟、波特率和串口助手 `8N1` |
| 一收数据就 HardFault | 缓冲区、栈、重复回调或错误 UART 句柄 |
| 浮点解析/输出异常 | 关闭 MicroLIB，确认运行库支持浮点 `sscanf/vsnprintf` |
| PC 拒绝 ACK | request ID、loop 或实际参数不一致 |
| PC 拒绝数据 | 时间戳、NaN、采样间隔或 error 字段不合法 |

完成移植后，先用 `scripts/monitor_serial.py` 和 `scripts/collect_data.py` 验证链路，
再运行在线调参。
