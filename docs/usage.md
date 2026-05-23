# Automatically-adjust-PID-parameters 使用指南

这份文档只讲怎么用，以及遇到问题时先查什么。

## 1. 最常见的三种用法

### 用法 1：先用仿真模式熟悉流程

```bash
python main.py simulate --loop speed --iterations 3
```

适合：

1. 还没有硬件
2. 想先看整体流程
3. 想先确认 LLM 调参大概会输出什么

### 用法 2：用离线模式分析已有数据

```bash
python main.py offline --file data/raw/example_speed_data.csv --loop speed
```

适合：

1. 你已经采到一份数据
2. 还不想直接在线改参数
3. 想先确认建议方向是否合理

### 用法 3：在线模式接真实 MCU

```bash
python main.py online --port COM3 --loop speed --interval 10
```

说明：

1. `COM3` 只是默认示例
2. 运行前改成你电脑上的实际串口

## 2. 第一次使用时怎么做最稳

推荐顺序：

1. 安装依赖
2. 复制本地配置
3. 跑帮助命令
4. 跑本地离线分析
5. 再跑仿真
6. 最后再接硬件

### 安装依赖

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 复制本地配置

```bash
copy config.example.json config.json
```

### 看帮助

```bash
python main.py --help
```

### 跑本地分析

```bash
python scripts/offline_analyze.py --file data/raw/example_speed_data.csv
```

这一步最值得先做，因为它不依赖：

1. 网络
2. API key
3. 串口
4. MCU

## 3. 配置文件怎么理解

### `config.example.json`

这是示例模板。

### `config.json`

这是你本地真正运行时使用的配置。第一次使用时从示例文件复制出来即可。

### API key 怎么放

你有两种方式：

1. 推荐：设置环境变量 `DEEPSEEK_API_KEY`
2. 兼容：写进本地 `config.json`

如果你用本地配置文件，重点看这段：

```json
"llm": {
  "api_key": "your-deepseek-api-key"
}
```

### 串口默认值怎么理解

示例配置里的串口默认是 `COM3`。

说明：

1. 这只是默认示例
2. 真正运行前改成你电脑上的实际串口

## 4. 离线数据格式是什么样

推荐 CSV 格式：

```csv
timestamp,target,actual,error,output
0.0000,100.0,0.0,100.0,500.0
0.0100,100.0,4.85,95.15,480.75
```

如果你只有前三列：

```csv
timestamp,target,actual
```

也可以，程序会自动补误差，输出值会记成 `0.0`。

## 5. 在线模式前先做什么

### 先监看串口

```bash
python scripts/monitor_serial.py --port COM3
```

你先确认：

1. 串口能打开
2. 设备持续发数据
3. 数据格式像 `DATA:<loop>:...`

这里的 `COM3` 只是默认示例，运行前改成你的实际串口。

### 再采一份数据

```bash
python scripts/collect_data.py --port COM3 --loop speed --duration 20
```

这里的 `COM3` 只是默认示例，运行前改成你的实际串口。

采完以后先做离线分析。把 `--file` 换成你刚采集出来的 CSV 文件路径。

## 6. 还可以用哪些辅助脚本

### 只做本地分析

```bash
python scripts/offline_analyze.py --file data/raw/example_speed_data.csv
```

### 监看串口

```bash
python scripts/monitor_serial.py --port COM3
```

### 采集串口数据

```bash
python scripts/collect_data.py --port COM3 --loop speed --count 500
```

### 画响应曲线

```bash
python scripts/visualize.py --file data/raw/example_speed_data.csv
```

### 画调参历史

先在 `data/logs/` 里选一份历史文件，再把它传给 `--history`。

### 导出 C 参数

```bash
python scripts/convert_to_code.py --loop speed
python scripts/convert_to_code.py --all --format struct
```

## 7. 输出结果怎么理解

常见指标：

1. `Overshoot`
超调量
2. `Settling time`
调节时间
3. `Steady-state error`
稳态误差
4. `Oscillation count`
振荡次数

可以这样理解：

1. 超调大，通常说明系统太猛
2. 调节时间长，通常说明响应慢
3. 稳态误差大，说明最后没贴住目标
4. 振荡多，通常说明参数偏激进

如果 LLM 调参成功，你还会看到：

1. 新的 `Kp/Ki/Kd`
2. 调整理由
3. 置信度
4. 一条可直接发给设备的串口命令

## 8. 最常见的问题

### `401 Authorization Required`

说明：

1. API key 无效
2. 没配置 key
3. 程序没有读到 key

处理：

1. 检查 `DEEPSEEK_API_KEY`
2. 或检查本地 `config.json`

### 串口打不开

处理：

1. 检查端口号
2. 检查波特率
3. 检查是否被其他软件占用

### 在线模式总是样本不足

处理：

1. 看 MCU 有没有持续发 `DATA:`
2. 看 `loop` 名称是否和命令行一致
3. 先用 `monitor_serial.py` 检查

### 离线模式直接退出

处理：

1. 看 CSV 是否至少有 5 条数据
2. 看列格式是否正确
3. 看文件是不是纯文本

## 9. 最后给一个稳妥顺序

如果你不想来回踩坑，建议始终按这个顺序：

1. 先证明本地分析能跑
2. 再证明 LLM key 没问题
3. 再证明 MCU 串口链路没问题
4. 最后才在线调参
