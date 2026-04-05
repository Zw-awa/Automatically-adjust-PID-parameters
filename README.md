# PID自动调参系统 - 基于LLM的智能PID参数优化

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 🎯 项目简介

这是一个基于大语言模型（LLM）的PID参数自动调优系统。通过DeepSeek API，系统能够智能分析控制系统的性能数据，自动调整PID控制器的Kp、Ki、Kd参数，实现最优控制效果。

### ✨ 核心特性

- **🤖 AI智能调参**：使用DeepSeek LLM理解控制原理，提供解释性调参建议
- **🔧 多模式支持**：在线实时调参、离线数据分析、软件仿真三种工作模式
- **📊 完整工具链**：数据收集、性能分析、可视化、代码生成一体化
- **🛡️ 多重安全保护**：参数限制、变化率限制、收敛检测、手动确认机制
- **🔌 硬件兼容**：标准串口协议，支持各种MCU平台

## 🚀 快速开始

### 1. 环境准备

确保已安装Python 3.8+，然后安装依赖：

```bash
# 克隆项目
git clone <项目地址>
cd pid_tuner_project

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置API密钥

编辑 `config.json` 文件：

```json
"llm": {
  "api_key": "你的DeepSeek-API密钥",  // 替换为你的API密钥
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-reasoner",
  "temperature": 0.3
}
```

> 💡 **获取API密钥**：访问 [DeepSeek官网](https://platform.deepseek.com/) 注册并获取API密钥

### 3. 首次测试（仿真模式）

无需硬件，快速验证系统功能：

```bash
# 测试速度环的PID调参
python main.py simulate --loop speed --iterations 3
```

### 4. 使用批处理脚本（Windows用户）

```bash
# 交互式在线调参
run_online.bat

# 交互式离线分析  
run_offline.bat
```

## 📖 详细使用指南

### 三种工作模式

#### 🎮 **仿真模式** - 无硬件测试
```bash
python main.py simulate --loop speed --iterations 5
```
- **适用场景**：学习、演示、算法验证
- **特点**：内置软件PID模型，无需真实硬件

#### 📁 **离线模式** - 数据分析
```bash
python main.py offline --file data/raw/example_speed_data.csv --loop speed
```
- **适用场景**：历史数据分析、参数优化
- **数据格式**：CSV文件，包含时间戳、目标值、实际值等

#### 🔌 **在线模式** - 实时调参
```bash
python main.py online --port COM3 --loop speed --interval 10
```
- **适用场景**：真实硬件系统调参
- **硬件要求**：MCU需实现指定串口协议

### 支持的控制环

系统预置4种常用控制环，可在 `config.json` 中配置：

| 环名称 | 中文名 | 典型应用 | 默认参数范围 |
|--------|--------|----------|--------------|
| `speed` | 速度环 | 电机转速控制 | Kp: 0.01-50 |
| `steering` | 转向环 | 舵机/方向控制 | Kp: 0.01-100 |
| `position` | 位置环 | 位置/距离控制 | Kp: 0.001-30 |
| `current` | 电流环 | 电机电流控制 | Kp: 0.001-10 |

### 串口通信协议

MCU端需要实现以下协议：

```c
// MCU -> PC: 发送数据
DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>\n
// 示例：DATA:speed:1.2345,100.0,95.3,-4.7,85.2\n

// PC -> MCU: 发送新参数  
PID:<loop>:<Kp>,<Ki>,<Kd>\n
// 示例：PID:speed:0.800000,0.150000,0.030000\n

// MCU -> PC: 确认接收
ACK:<loop>:<Kp>,<Ki>,<Kd>\n
```

完整MCU参考代码见：`docs/mcu_reference.c`

## 🛠️ 工具脚本

项目提供多个实用脚本：

| 脚本文件 | 功能描述 | 使用示例 |
|----------|----------|----------|
| `scripts/monitor_serial.py` | 串口数据监控 | `python scripts/monitor_serial.py COM3` |
| `scripts/collect_data.py` | 数据采集到CSV | `python scripts/collect_data.py COM3 speed` |
| `scripts/offline_analyze.py` | 离线数据分析 | `python scripts/offline_analyze.py data.csv` |
| `scripts/visualize.py` | 性能曲线可视化 | `python scripts/visualize.py --history` |
| `scripts/convert_to_code.py` | 生成C代码 | `python scripts/convert_to_code.py speed` |

## 📁 项目结构

```
pid_tuner_project/
├── core/                    # 核心模块
│   ├── tuner.py            # LLM调参核心
│   ├── serial_manager.py   # 串口通信
│   ├── data_collector.py   # 数据收集
│   ├── analyzer.py         # 性能分析
│   ├── history_manager.py  # 历史管理
│   └── config.py           # 配置管理
├── scripts/                # 工具脚本
├── docs/                   # 文档
├── data/                   # 数据目录
│   ├── raw/               # 原始数据
│   ├── processed/         # 处理数据
│   └── logs/              # 日志文件
├── outputs/               # 输出目录
│   ├── figures/           # 图表
│   └── reports/           # 报告
├── tests/                 # 测试文件
├── main.py               # 主程序入口
├── config.json           # 配置文件
├── requirements.txt      # 依赖列表
└── README.md            # 本文档
```

## 🔧 配置详解

### 主要配置项

```json
{
  "serial": {
    "port": "COM3",           // 串口号
    "baudrate": 115200,       // 波特率
    "timeout": 1.0            // 超时时间(秒)
  },
  "tuning": {
    "max_change_ratio": 0.2,  // 最大变化率(20%)
    "convergence_patience": 3 // 收敛检测次数
  },
  "online": {
    "tune_interval_s": 10,    // 调参间隔(秒)
    "auto_apply": false       // 是否自动应用参数
  }
}
```

### 添加自定义控制环

在 `config.json` 的 `loops` 部分添加：

```json
"your_loop": {
  "name": "自定义环",
  "pid": {"kp": 1.0, "ki": 0.1, "kd": 0.05},
  "limits": {"kp": [0.1, 10.0], "ki": [0.0, 5.0], "kd": [0.0, 2.0]},
  "target_metrics": {
    "max_overshoot_pct": 10.0,    // 最大超调量(%)
    "max_settling_time_s": 1.0,   // 最大调节时间(秒)
    "max_sse_pct": 2.0           // 最大稳态误差(%)
  }
}
```

## 🛡️ 安全机制

1. **参数范围限制**：每个PID参数都有最小/最大值
2. **变化率限制**：单次调参最多改变20%（可配置）
3. **收敛自动停止**：连续3次"已收敛"则停止调参
4. **手动确认机制**：在线模式默认需要人工确认
5. **振荡检测**：历史管理器检测参数振荡并警告
6. **MCU端保护**：参考代码包含参数范围检查

## ❓ 常见问题

### Q1: 如何获取DeepSeek API密钥？
A: 访问 https://platform.deepseek.com/ 注册账号，在控制台创建API密钥。

### Q2: 串口连接失败怎么办？
A: 检查：
1. 串口号是否正确（Windows: COM3, Linux: /dev/ttyUSB0）
2. 波特率是否匹配（默认115200）
3. 串口线是否正常连接
4. 是否有其他程序占用串口

### Q3: 数据格式要求？
A: CSV文件需要包含以下列：
```
timestamp,target,actual,error,output
0.0000,100.0,0.0,100.0,500.0
0.0100,100.0,4.85,95.15,480.75
```

### Q4: 如何查看调参历史？
A: 使用可视化脚本：
```bash
python scripts/visualize.py --history
```

### Q5: 调参效果不理想？
A: 尝试：
1. 调整目标性能指标（降低超调量要求等）
2. 增加数据采样数量
3. 检查数据质量（噪声、采样率等）
4. 手动调整初始参数

## 📈 性能指标

系统分析以下关键指标：
- **超调量** (Overshoot)：响应超过目标值的百分比
- **调节时间** (Settling Time)：进入稳态所需时间
- **稳态误差** (Steady-State Error)：稳定后的误差百分比
- **振荡次数** (Oscillations)：响应曲线的振荡次数

## 🤝 贡献指南

欢迎提交Issue和Pull Request！贡献前请：
1. 阅读代码规范
2. 添加相应的测试
3. 更新相关文档

## 📄 许可证

本项目基于 MIT 许可证开源 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- 感谢 DeepSeek 提供强大的LLM API
- 感谢所有贡献者和用户的支持
- 特别感谢开源社区的各种工具和库

---

**开始你的智能PID调参之旅吧！** 🚀

如果有任何问题，请查看详细文档或提交Issue。