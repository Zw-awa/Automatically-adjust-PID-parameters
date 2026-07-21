# STM32 PID 调参示例

这两个示例面向已经做过 GPIO、定时器或循迹小车项目，但还不熟悉模块移植的 STM32 用户。
它们先用一个安全的软件一阶对象验证通信和 PID 流程，不会输出 PWM，也不会驱动电机。

## 先选一个工程

| 工程 | 适合场景 | 工程文件 |
| --- | --- | --- |
| STM32F103 标准库版 | 常见 F103C8T6/F103C8 开发板、学习标准库 | `stm32f103_stdperiph_pid_tuner/PID_Tuner_Std.uvprojx` |
| STM32G431 HAL 版 | 新项目、CubeMX/HAL 用户 | `stm32g431_hal_pid_tuner/MDK-ARM/PID_Tuner_HAL.uvprojx` |

第一次只需要选择与你手上芯片一致的一套，不需要同时学习两套代码。

## 10 分钟快速开始

1. 安装 Keil MDK、对应 STM32 Device Pack 和 ST-Link 驱动。
2. 双击对应的 `.uvprojx`，在 Keil 中按 `F7` 编译。
3. 用 ST-Link 下载，不要修改代码中的软件对象配置。
4. 用 3.3 V TTL 串口接线：开发板 TX 接 USB 串口 RX，开发板 RX 接 USB 串口 TX，GND 共地。
5. 串口助手设置 `115200 8N1`，关闭硬件流控。
6. 复位开发板，应该看到一行 `INFO:READY`，随后持续看到 `DATA:speed`。

手动发送下面的命令可以验证参数更新：

```text
PID:req001:speed:1.200000,0.100000,0.050000
```

设备应返回匹配的：

```text
ACK:req001:speed:1.200000,0.100000,0.050000
```

这一步不需要 Python，也不需要 Git。Python 脚本用于后续自动采集、离线分析和在线调参。

## 初始化清单

| 项目 | 标准库版 | HAL 版 |
| --- | --- | --- |
| 芯片时钟 | `SystemCoreClockUpdate()` | `HAL_Init()` + `SystemClock_Config()` |
| UART/GPIO | `PidTunerPort.c` 内初始化 USART1、PA9/PA10 | CubeMX 生成 `MX_USART1_UART_Init()` |
| 中断 | `USART1_IRQHandler()` 转发一行 | `HAL_UART_IRQHandler()` + HAL 回调转发 |
| 时间基准 | `PidTunerPort.c` 配置 1 ms SysTick | 使用 `HAL_GetTick()` |
| 主循环 | `PIDTuner_Poll()` 持续调用 | `PIDTuner_Poll()` 持续调用 |

只要缺少其中一项，常见结果就是没有 `DATA`、没有 `ACK` 或串口乱码。

## 代码应该看什么

不要从 `Library/`、`Drivers/` 或 `Start/` 开始阅读。第一次只看以下文件：

| 文件 | 是否修改 | 用途 |
| --- | --- | --- |
| `PidTuner.c` / `pid_tuner.c` | 否 | PID、协议、参数边界、ACK/NACK |
| `PidTunerConfig.h` / `pid_tuner_config.h` | 是 | 环名称、周期、初始参数、输出限幅 |
| `PidTunerPort.c` / `pid_tuner_port.c` | 通常不改 | UART、缓冲区、时基和中断适配 |
| `PidTunerUser.c` / `pid_tuner_user.c` | 是 | 目标值、传感器值、PWM/执行器输出 |
| `stm32f10x_it.c` 或 `pid_tuner_callbacks.c` | 合并 | 把已有中断/回调转发给调参模块 |

## 移植到自己的工程

1. 复制核心文件、配置文件、端口文件和用户接口文件。
2. 把 `.c` 文件加入 Keil 工程，把对应目录加入 Include Paths。
3. 先保证 UART 已完成初始化，再调用 `PIDTuner_Init()`。
4. 在主循环中持续调用 `PIDTuner_Poll()`。
5. 如果已有 USART 中断或 HAL 回调，不要再定义第二份函数，只加入对应的转发调用。
6. 先保持 `PID_TUNER_USE_SOFTWARE_PLANT` 为 `1`，确认协议正常后再改为 `0`。
7. 只修改用户接口中的三个函数：读取目标、读取实际值、写入输出。

真实电机接入时，必须另外加入输出限幅、过流保护、超速保护、急停、传感器异常处理和看门狗。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 工程打不开 | 使用工程目录中的 `.uvprojx`，不要直接打开 `.ioc`；确认文件没有被文本编辑器改成带 BOM 的 XML |
| 编译找不到头文件 | 是否加入了核心、端口、用户文件所在目录 |
| 没有 `INFO:READY` | `PIDTuner_Init()` 是否在 UART 初始化之后调用 |
| 有 `INFO` 没有 `DATA` | 主循环是否持续调用 `PIDTuner_Poll()` |
| 有 `DATA` 没有 `ACK` | RX/TX 是否交叉、GND 是否共地、USART 中断/回调是否转发 |
| 串口乱码 | 波特率、系统时钟和串口助手的 `8N1` 设置是否一致 |
| `sscanf` 或浮点格式化异常 | Keil 不要启用 MicroLIB，使用支持浮点 `sscanf`/`vsnprintf` 的 C 运行库 |
