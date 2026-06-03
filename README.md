# Automatically-adjust-PID-parameters

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Serial-lightgrey.svg)](LICENSE)

Automatically-adjust-PID-parameters 用来根据控制响应数据给出下一轮 PID 参数建议。

它更适合这样使用：

1. 先用本地分析确认数据和环境没问题
2. 再用仿真模式熟悉调参流程
3. 最后把同一套流程接到真实 MCU 串口上

## 这个项目是什么

这个项目不是 MCU 控制器本体，而是一个调参助手。

它会做这些事：

1. 读取一段控制响应数据
2. 计算超调量、调节时间、稳态误差等指标
3. 把当前 PID、目标要求和历史记录交给模型
4. 给出下一轮 `Kp / Ki / Kd` 建议
5. 在在线模式下把新参数发回设备

你可以把它理解成：

1. 仿真模式下的调参练习工具
2. 离线模式下的数据分析工具
3. 在线模式下的串口调参工具

## 项目特色

### 1. 使用路径是逐步展开的

这个项目强调先把每一层单独跑通，再进入下一层：

1. 先本地分析
2. 再仿真
3. 再监看串口
4. 最后在线调参

这样更容易判断问题到底出在：

1. 数据本身
2. API key
3. 串口链路
4. 设备侧实现

### 2. 硬件接入路径直接

项目围绕最常见的串口接入方式组织流程。

你可以直接使用：

1. `monitor_serial.py` 做串口联调
2. `collect_data.py` 先采一份数据
3. 离线模式先看指标和建议
4. `docs/mcu_reference.c` 作为 STM32 HAL 参考

对 STM32 来说，参考代码已经把这些入口提成宏：

1. UART 句柄
2. TX/RX 引脚
3. 控制环名字

### 3. 安全策略放在前面

这个项目默认不是“算完就直接改参数”，而是先控制风险。

当前默认策略包括：

1. 参数上下限限制
2. 单次变化率限制
3. 历史记录辅助判断
4. 在线模式默认人工确认
5. 等待设备 `ACK` 确认

## 运行前需要改什么

第一次使用前，至少确认这几项：

1. 复制 `config.example.json` 为 `config.json`
2. 配置 `DEEPSEEK_API_KEY`，或者把 key 写进本地 `config.json`
3. 如果你要接在线模式，把默认 `COM3` 改成你电脑上的实际串口
4. 如果你要接真实设备，确认 MCU 发出的控制环名字和本地配置一致

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/Zw-awa/Automatically-adjust-PID-parameters.git
cd Automatically-adjust-PID-parameters
```

### 2. 安装依赖

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

建议使用 Python 3.10 或更高版本。

### 3. 复制本地配置

```bash
copy config.example.json config.json
```

### 4. 先跑本地分析

```bash
python scripts/offline_analyze.py --file data/raw/example_speed_data.csv
```

这一步最适合先做，因为它不依赖：

1. API key
2. 串口
3. MCU

### 5. 再跑仿真

```bash
python main.py simulate --loop speed --iterations 1
```

如果 API key 还没配好，这一步可能会在最后的 LLM 调用时报错。先看前面的分析输出是否正常。

## 三种模式

### 仿真模式

```bash
python main.py simulate --loop speed --iterations 3
```

适合：

1. 第一次上手
2. 没有硬件时先看流程
3. 想先确认参数建议长什么样

### 离线模式

```bash
python main.py offline --file data/raw/example_speed_data.csv --loop speed
```

适合：

1. 你已经采到一份数据
2. 想先分析数据再决定是否在线调参

### 在线模式

```bash
python main.py online --port COM3 --loop speed --interval 10
```

说明：

1. `COM3` 只是默认示例
2. 运行前改成你电脑上的实际串口

## 实验控制台

如果你想把调参过程做成“可观察的实验台”，可以直接启动本地实验控制台：

```bash
python main.py lab
```

或者：

```bash
python scripts/start_lab.py
run_lab.bat
```

当前控制台能力：

1. 本地 Web GUI
2. 会话命名、编辑、删除
3. 每轮记录自动保存到本地 SQLite
4. 支持 `llm / bo / hybrid` 三种策略
5. 支持仿真自动多轮实验
6. 支持离线 CSV 基线导入和手动补录
7. 实时表格、事件流、趋势图和参数空间散点图

当前边界：

1. 第一阶段只覆盖 `simulate` 和 `offline`
2. 在线 MCU GUI 接入还没实现
3. 第二阶段接入方案见 `docs/private/experimental_lab_phase2_online_plan.md`

## 常用脚本

### 监看串口

```bash
python scripts/monitor_serial.py --port COM3
```

`COM3` 只是默认示例，运行前改成你的实际串口。

### 采集串口数据

```bash
python scripts/collect_data.py --port COM3 --loop speed --duration 20
```

`COM3` 只是默认示例，运行前改成你的实际串口。

### 只做本地分析

```bash
python scripts/offline_analyze.py --file data/raw/example_speed_data.csv
```

### 画响应曲线

```bash
python scripts/visualize.py --file data/raw/example_speed_data.csv
```

### 画调参历史

先在 `data/logs/` 里选一份历史文件，再把它传给 `--history`。

### 启动实验控制台

```bash
python main.py lab
python scripts/start_lab.py --no-browser
```

### 导出 C 参数

```bash
python scripts/convert_to_code.py --loop speed
python scripts/convert_to_code.py --all --format struct
```

## 项目结构

```text
Automatically-adjust-PID-parameters/
├── core/                 核心逻辑
├── scripts/              辅助脚本
├── docs/                 使用文档和 STM32 参考代码
├── data/                 示例数据和运行数据目录
├── site/                 静态说明页
├── tests/                本地测试
├── main.py               主入口
├── config.example.json   示例配置
├── requirements.txt      依赖列表
└── README.md
```

## STM32 接入

如果你要接 STM32：

1. 先看 `docs/MCU集成指南.md`
2. 再看 `docs/mcu_reference.c`

`docs/mcu_reference.c` 已经按 STM32 HAL 风格写成参考实现，UART 句柄、TX/RX 引脚和环名字都可以通过宏统一改。

## 常见问题

### `401 Authorization Required`

通常表示：

1. API key 无效
2. 没配置 key
3. 程序没有读到 key

### 串口打不开

通常先检查：

1. 端口号是否正确
2. 波特率是否一致
3. 是否被其他程序占用

### 在线模式总是样本不足

通常先检查：

1. MCU 是否持续发送 `DATA:`
2. `loop` 名称是否一致
3. 串口监看脚本里有没有正常数据

## 许可证

本项目使用 MIT License。详见 [LICENSE](LICENSE)。
