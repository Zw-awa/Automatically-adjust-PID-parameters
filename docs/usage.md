# PID自动调参系统 - 使用指南

## 🎯 写给小白用户

如果你是第一次接触PID调参或这个项目，不用担心！本指南将手把手教你如何使用这个系统。即使你没有任何PID控制经验，也能跟着步骤完成调参。

### 你需要准备什么？

1. **一台电脑**：Windows/Mac/Linux都可以
2. **Python环境**：版本3.8或以上
3. **网络连接**：用于访问DeepSeek API
4. **（可选）硬件**：如果要进行真实调参，需要MCU开发板

## 🚀 5分钟快速上手

### 第1步：安装Python（如果还没安装）

**Windows用户**：
1. 访问 https://www.python.org/downloads/
2. 下载Python 3.8+版本
3. 安装时记得勾选"Add Python to PATH"

**验证安装**：
```bash
python --version
# 应该显示 Python 3.8.x 或更高版本
```

### 第2步：下载项目并安装依赖

```bash
# 1. 进入你的项目文件夹（比如桌面）
cd Desktop

# 2. 克隆或下载项目（如果你已经下载了，跳过这步）
# 假设项目文件夹叫 pid_tuner_project

# 3. 进入项目文件夹
cd pid_tuner_project

# 4. 安装所需软件包
pip install -r requirements.txt
```

> 💡 **如果pip安装慢**：可以使用国内镜像源
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

### 第3步：获取API密钥

1. 访问 https://platform.deepseek.com/
2. 注册账号并登录
3. 在控制台找到"API Keys"（API密钥）
4. 点击"Create new API key"（创建新API密钥）
5. 复制生成的密钥

### 第4步：配置项目

用文本编辑器打开 `config.json` 文件，找到这一部分：

```json
"llm": {
  "api_key": "your-deepseek-api-key",  // ← 把这里替换成你的API密钥
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-reasoner"
}
```

把 `"your-deepseek-api-key"` 替换成你刚才复制的真实API密钥。

### 第5步：第一次运行（仿真模式）

现在可以测试系统了！输入以下命令：

```bash
python main.py simulate --loop speed --iterations 2
```

你会看到类似这样的输出：
```
============================================================
  PID Auto-Tuner - Simulation Mode
  Loop: speed
  Iterations: 2
============================================================

----------------------------------------
  Simulation iteration #1
  PID: Kp=1.0000 Ki=0.1000 Kd=0.0500
----------------------------------------
Performance Metrics:
  Overshoot: 15.2%
  Settling Time: 0.42s
  Steady-State Error: 0.8%
  Oscillations: 2

Consulting LLM...

----------------------------------------
  LLM Analysis (deepseek-reasoner):
  Confidence: 85%
  Reason: 超调量偏高，建议减小Kp，增加Kd来抑制振荡
...
```

**恭喜！** 🎉 你已经成功运行了PID自动调参系统！

## 📖 详细使用说明

### 三种工作模式详解

#### 1. 🎮 **仿真模式** - 最适合新手

**什么时候用？**
- 学习PID调参原理
- 测试系统功能
- 演示给其他人看
- 没有硬件设备时

**常用命令**：
```bash
# 基本用法
python main.py simulate --loop speed --iterations 3

# 测试不同控制环
python main.py simulate --loop steering --iterations 2
python main.py simulate --loop position --iterations 2
python main.py simulate --loop current --iterations 2

# 更多迭代次数（更精确）
python main.py simulate --loop speed --iterations 5
```

**仿真模式特点**：
- ✅ 无需硬件
- ✅ 快速得到结果
- ✅ 安全，不会损坏设备
- ✅ 可以反复试验

#### 2. 📁 **离线模式** - 分析已有数据

**什么时候用？**
- 你已经有了一些控制系统的运行数据
- 想优化现有PID参数
- 需要生成调参报告

**数据准备**：
1. 数据需要保存为CSV格式
2. 文件放在 `data/raw/` 文件夹
3. 格式要求：

```
timestamp,target,actual,error,output
0.0000,100.0,0.0,100.0,500.0
0.0100,100.0,4.85,95.15,480.75
0.0200,100.0,9.42,90.58,462.9
...
```

**运行命令**：
```bash
# 分析示例数据
python main.py offline --file data/raw/example_speed_data.csv --loop speed

# 分析你自己的数据
python main.py offline --file data/raw/你的数据.csv --loop speed
```

**输出结果**：
- 性能分析报告
- LLM调参建议
- 新的PID参数
- 可以直接复制到MCU的串口命令

#### 3. 🔌 **在线模式** - 实时硬件调参

**什么时候用？**
- 你有真实的硬件系统（电机、机器人等）
- 需要实时优化参数
- 系统正在运行中

**硬件准备**：
1. MCU开发板（Arduino、STM32等）
2. 串口连接线（USB转TTL）
3. 在MCU上运行 `docs/mcu_reference.c` 中的代码

**运行命令**：
```bash
# Windows用户（串口通常是COM3、COM4等）
python main.py online --port COM3 --loop speed --interval 10

# Linux/Mac用户（串口通常是/dev/ttyUSB0、/dev/ttyACM0等）
python main.py online --port /dev/ttyUSB0 --loop speed --interval 10
```

**参数说明**：
- `--port`：串口号
- `--loop`：控制环类型
- `--interval`：调参间隔（秒），默认10秒

**在线模式流程**：
1. 系统每10秒收集一次数据
2. 分析数据性能
3. 询问LLM获取调参建议
4. 询问你是否要应用新参数（按y确认）
5. 发送新参数到MCU
6. 重复这个过程直到参数收敛

### 🎯 控制环选择指南

系统支持4种控制环，根据你的应用选择：

| 环类型 | 适用场景 | 典型设备 | 新手建议 |
|--------|----------|----------|----------|
| **速度环** | 电机转速控制 | 直流电机、步进电机 | ✅ 最适合新手 |
| **转向环** | 方向控制 | 舵机、差速转向 | ✅ 比较容易 |
| **位置环** | 位置控制 | 机械臂、线性导轨 | ⚠️ 需要更多经验 |
| **电流环** | 电流控制 | 电机驱动器 | 🔧 高级用户 |

**新手建议**：从速度环开始，它最直观也最容易理解。

### ⚙️ 配置文件详解

`config.json` 是项目的核心配置文件，主要部分：

#### 串口配置（在线模式需要）
```json
"serial": {
  "port": "COM3",      // 串口号
  "baudrate": 115200,  // 波特率（和MCU一致）
  "timeout": 1.0,      // 超时时间（秒）
  "encoding": "utf-8"  // 编码格式
}
```

#### 调参参数
```json
"tuning": {
  "max_change_ratio": 0.2,      // 最大变化率20%（安全限制）
  "min_change_threshold": 0.01, // 最小变化阈值
  "history_window": 10,         // 历史记录窗口
  "data_sample_count": 50,      // 每次分析的数据点数
  "convergence_patience": 3     // 连续3次收敛就停止
}
```

#### 在线模式参数
```json
"online": {
  "tune_interval_s": 10,    // 调参间隔10秒
  "data_buffer_size": 200,  // 数据缓冲区大小
  "auto_apply": false       // 是否自动应用（新手建议false）
}
```

### 🛠️ 实用工具脚本

项目提供了多个方便的工具：

#### 1. 串口监控器
```bash
# 查看串口数据（不调参）
python scripts/monitor_serial.py COM3
```
**用途**：检查MCU是否正常发送数据

#### 2. 数据采集器
```bash
# 采集数据保存到CSV
python scripts/collect_data.py COM3 speed
```
**用途**：录制运行数据，用于离线分析

#### 3. 可视化工具
```bash
# 查看性能曲线
python scripts/visualize.py

# 查看调参历史
python scripts/visualize.py --history

# 保存图表到文件
python scripts/visualize.py --save
```
**用途**：直观理解系统性能

#### 4. 代码生成器
```bash
# 生成C语言PID参数代码
python scripts/convert_to_code.py speed
```
**用途**：将优化后的参数直接嵌入MCU代码

### 📊 理解性能指标

系统会分析这些关键指标：

| 指标 | 中文名 | 理想值 | 说明 |
|------|--------|--------|------|
| **Overshoot** | 超调量 | < 5% | 响应超过目标值的百分比，越小越好 |
| **Settling Time** | 调节时间 | < 1秒 | 进入稳态所需时间，越短越好 |
| **Steady-State Error** | 稳态误差 | < 2% | 稳定后的误差，越小越好 |
| **Oscillations** | 振荡次数 | 0-2次 | 响应曲线的振荡次数，越少越好 |

**新手目标**：先让超调量<10%，调节时间<2秒，就是不错的开始！

### 🆘 故障排除

#### 问题1：API密钥错误
```
ERROR: LLM call failed: Authentication error
```
**解决**：检查 `config.json` 中的 `api_key` 是否正确

#### 问题2：串口打不开
```
ERROR: Could not open port COM3
```
**解决**：
1. 检查串口号是否正确
2. 检查串口线是否连接
3. 关闭其他占用串口的软件（如Arduino IDE）

#### 问题3：没有数据
```
Insufficient data (0 samples), waiting...
```
**解决**：
1. 检查MCU是否在发送数据
2. 使用 `monitor_serial.py` 验证数据
3. 检查波特率设置是否一致

#### 问题4：调参效果不好
**解决**：
1. 增加数据采样数量（`data_sample_count`）
2. 调整目标性能指标（放宽要求）
3. 检查数据质量（噪声太大影响分析）

### 💡 实用技巧

#### 技巧1：从仿真开始
即使有硬件，也先用仿真模式熟悉流程。

#### 技巧2：保存历史
每次调参的历史都保存在 `outputs/reports/`，可以随时查看。

#### 技巧3：批量测试
```bash
# 测试不同初始参数
python main.py simulate --loop speed --iterations 3
# 修改config.json中的初始参数
python main.py simulate --loop speed --iterations 3
```

#### 技巧4：使用批处理脚本（Windows）
双击 `run_online.bat` 或 `run_offline.bat`，按提示操作即可。

### 🎓 学习资源

如果你想深入学习PID控制：

1. **PID基础**：搜索"PID控制入门教程"
2. **参数整定**：了解Ziegler-Nichols方法
3. **实际应用**：查看机器人、无人机中的PID应用案例
4. **进阶学习**：学习现代控制理论（如MPC、LQR）

### 📞 获取帮助

如果遇到问题：

1. **查看本文档**：大部分问题这里都有解答
2. **检查错误信息**：错误信息通常能指出问题所在
3. **简化测试**：先用仿真模式排除硬件问题
4. **搜索类似问题**：很多问题别人已经遇到过

---

## 🏁 下一步行动

现在你已经掌握了基本用法，建议按这个顺序实践：

1. ✅ **完成**：仿真模式测试（2-3次迭代）
2. 🔄 **尝试**：修改初始参数，观察变化
3. 📊 **进阶**：使用可视化工具查看曲线
4. 🔌 **实战**：连接真实硬件进行在线调参

**记住**：PID调参既是科学也是艺术，需要耐心和实践。这个工具能大大简化过程，但理解原理会让你用得更好。

**祝你调参顺利！** 🚀

如果有文档未覆盖的问题，欢迎反馈！