# Automatically-adjust-PID-parameters

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Serial-lightgrey.svg)](LICENSE)

一个面向仿真、离线数据和 MCU 串口的 PID 分析与调参助手。

它负责读取控制响应、计算性能指标、生成下一轮 PID 建议，并在在线模式中通过
协议 v2 安全地下发参数。真正的实时控制、传感器采集、PWM 和硬件保护仍由 MCU 负责。

## 按目标选择入口

| 你的目标 | 从这里开始 | 是否需要 Python |
| --- | --- | --- |
| 第一次运行 PC 工具 | [快速入门](docs/快速入门指南.md) | 是 |
| 查看全部命令和配置 | [使用手册](docs/usage.md) | 是 |
| 先在 STM32 上跑通 UART/PID demo | [STM32 示例](examples/README.md) | 否 |
| 把调参模块移植进自己的小车 | [MCU 集成指南](docs/MCU集成指南.md) | 联调前不需要 |
| 理解内部数据流和安全边界 | [架构说明](docs/architecture.md) | 否 |
| 使用本地实验控制台 | [使用手册：实验控制台](docs/usage.md#实验控制台) | 是 |

完整导航见 [文档索引](docs/文档索引.md)。

## 能做什么

- 分析超调量、调节时间、稳态误差、振荡、饱和和数据质量。
- 从软件仿真、CSV 或 MCU 串口获取控制响应。
- 结合当前 PID、目标指标和历史记录生成参数建议。
- 限制参数范围和单次变化幅度。
- 使用 request ID、ACK/NACK 和实际生效值确认在线更新。
- 通过本地实验控制台比较 LLM、BO 和 hybrid 策略。

它不是自动保证稳定的控制器，也不能替代过流、超速、急停、看门狗和回滚机制。

## PC 端快速开始

需要 Python 3.10 或更高版本。

```bat
python -m pip install -r requirements.txt
python scripts/offline_analyze.py --file data/raw/example_speed_data.csv
```

第二条命令只做本地指标分析，不需要 API key、串口或 MCU，最适合验证安装是否正常。

需要 LLM 建议时，再复制本地配置并设置 DeepSeek API key：

```bat
copy config.example.json config.json
python main.py simulate --loop speed --iterations 1
```

推荐通过环境变量 `DEEPSEEK_API_KEY` 提供密钥；`config.json` 已被 Git 忽略，
也可以只在本机写入密钥。

## 四种运行方式

| 模式 | 命令 | 数据来源 | API key |
| --- | --- | --- | --- |
| 本地指标分析 | `python scripts/offline_analyze.py --file <csv>` | CSV | 不需要 |
| 仿真调参 | `python main.py simulate --loop speed --iterations 3` | 软件模型 | 需要 |
| 离线调参 | `python main.py offline --file <csv> --loop speed` | CSV | 需要 |
| 在线调参 | `python main.py online --port COM3 --loop speed` | MCU 串口 | 需要 |

`COM3` 只是示例，必须换成实际串口。在线模式默认 `auto_apply: false`，建议保持人工确认。

## STM32 接入

仓库提供两套经过 Keil 5.38 / ARMCC 5.06 实际构建的工程：

- STM32F103C8 标准库版：`examples/stm32f103_stdperiph_pid_tuner`
- STM32G431RBT6 HAL 版：`examples/stm32g431_hal_pid_tuner`

它们默认控制板内软件对象，不输出 PWM。第一次只用 Keil 和串口助手即可验证：

```text
INFO:READY:speed:...
DATA:speed:...
```

确认通信后，再按 [MCU 集成指南](docs/MCU集成指南.md) 修改用户接口接入真实传感器和执行器。

## 协议 v2

```text
MCU -> PC  DATA:<loop>:<time>,<target>,<actual>,<error>,<output>
PC  -> MCU PID:<request_id>:<loop>:<kp>,<ki>,<kd>
MCU -> PC  ACK:<request_id>:<loop>:<applied_kp>,<applied_ki>,<applied_kd>
MCU -> PC  NACK:<request_id>:<loop>:<reason>
```

PC 只有在 request ID、控制环和实际生效参数全部匹配时才接受 ACK。

## 项目结构

```text
core/               分析、配置、串口、调参和工作流
experimental_lab/   本地实验服务
lab_shell/          实验控制台前端资源
scripts/            采集、监视、分析、可视化和导出脚本
examples/           STM32 标准库/HAL 教学工程
docs/               使用、移植和架构文档
data/               示例数据和本地运行数据
tests/              单元与流程测试
main.py             PC 端统一入口
```

## 安全原则

- 先跑本地分析，再仿真，再串口监视，最后在线调参。
- CSV 必须有递增时间戳、有限数值和一致的 `error = target - actual`。
- `output_limits` 必须与固件真实输出范围和单位一致。
- 参数只应在控制周期边界生效，超时或不匹配的 ACK 都视为失败。
- 第一次实机联调时禁用执行器输出和自动应用。

## 许可证

项目自有代码使用 MIT License。STM32 示例内的 ST/Arm 文件保留各自原始许可，
具体边界见 `REUSE.toml`、`LICENSES/` 和示例目录中的第三方说明。
