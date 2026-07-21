# 使用手册

本页是 PC 端命令、配置、CSV 和故障排查的参考手册。第一次运行建议先看
[快速入门指南](快速入门指南.md)。

## 主程序

统一入口：

```bat
python main.py [--config PATH] [--verbose] <mode> [options]
```

如果没有显式指定配置，程序优先读取 `config.json`；文件不存在时回退到
`config.example.json`。

### 仿真模式

```bat
python main.py simulate --loop speed --iterations 3
```

使用软件对象生成响应，然后执行分析和 LLM 调参。需要有效 API key，不需要硬件。

### 离线调参

```bat
python main.py offline --file data/raw/example_speed_data.csv --loop speed
```

读取 CSV、分析数据、调用 LLM 并保存建议。可通过 `--history <json>` 继续使用
已有历史。仅想计算指标、不调用 LLM 时使用：

```bat
python scripts/offline_analyze.py --file data/raw/example_speed_data.csv
```

### 在线调参

```bat
python main.py online --port COM3 --loop speed --interval 10 --max-iter 5
```

`COM3` 必须换成实际端口。推荐保持 `online.auto_apply` 为 `false`，由用户确认后
再发送参数。设备只有返回完全匹配的协议 v2 ACK，本地配置才会接受新参数。

## 串口联调脚本

### 监视原始消息

```bat
python scripts/monitor_serial.py --port COM3 --baud 115200
```

确认持续收到 `DATA:<loop>:...`，并观察 ACK、NACK 和 INFO。

### 采集 CSV

按时间采集：

```bat
python scripts/collect_data.py --port COM3 --loop speed --duration 20
```

按样本数量采集：

```bat
python scripts/collect_data.py --port COM3 --loop speed --count 500
```

建议先采集、离线检查数据，再运行在线调参。

## 其他脚本

```bat
python scripts/visualize.py --file <csv>
python scripts/convert_to_code.py --loop speed
python scripts/convert_to_code.py --all --format struct
```

Windows 用户也可以使用：

- `run_offline.bat`
- `run_online.bat`
- `run_lab.bat`

## 配置文件

先复制模板：

```bat
copy config.example.json config.json
```

### `serial`

- `port`：串口名，例如 `COM3`。
- `baudrate`：必须与 MCU 一致，示例为 115200。
- `timeout`：串口读取超时秒数。
- `encoding`：协议文本编码，示例为 UTF-8/ASCII 兼容内容。

### `llm`

- `api_key`：推荐改用环境变量 `DEEPSEEK_API_KEY`。
- `base_url`：OpenAI 兼容 API 地址。
- `model` / `model_fallback`：主模型和回退模型。
- `temperature` / `max_tokens`：模型生成参数。

### `loops.<name>`

- `pid`：当前 `kp/ki/kd`。
- `limits`：PID 参数允许范围。
- `output_limits`：真实执行器输出范围，单位必须与 MCU 的 `output` 字段一致。
- `target_metrics`：最大超调、最大调节时间和最大稳态误差目标。

`limits` 约束 PID 参数；`output_limits` 用于检查执行器饱和，二者不是一回事。

### `tuning`

- `max_change_ratio`：单轮最大相对变化。
- `min_change_threshold`：过小变化吸附为原值。
- `history_window`：提供给调参逻辑的历史窗口。
- `data_sample_count`：提供给模型的采样数量。

### `online`

- `tune_interval_s`：在线调参间隔。
- `data_buffer_size`：内存中的采样缓冲区大小。
- `auto_apply`：是否自动发送建议；实机初期应为 `false`。

## CSV 格式

推荐五列：

```csv
timestamp,target,actual,error,output
0.000,100.0,0.0,100.0,0.0
0.010,100.0,4.8,95.2,50.0
```

也接受三列 `timestamp,target,actual`，程序会计算 error，并把 output 记为 0。

分析前会检查：

- 至少 10 个样本。
- 所有值有限，不允许 NaN/Infinity。
- 时间戳严格递增。
- 最大采样间隔不超过中位周期的 5 倍。
- `error` 与 `target - actual` 一致。
- 配置了输出范围时，检查输出是否饱和。

## 实验控制台

启动本地实验台：

```bat
python main.py lab
```

或者：

```bat
python scripts/start_lab.py --no-browser
run_lab.bat
```

当前支持 simulate/offline 会话、LLM/BO/hybrid 策略、本地 SQLite、记录表、
事件流和趋势图。真实 MCU 的在线 GUI 闭环尚未完成，命令行 online 模式不受影响。

## 输出文件

- 调参历史：`data/logs/`
- 实验数据库：`data/lab/`
- 串口采集：默认位于 `data/raw/` 或命令指定路径
- 图表和报告：`outputs/`

这些运行产物大多已被 `.gitignore` 忽略。

## 常见问题

### `401 Authorization Required`

检查 API key、环境变量和 base URL。`offline_analyze.py` 不需要 API key，可用来区分
本地分析问题与模型鉴权问题。

### 串口打不开

检查端口号、波特率、USB 驱动，以及串口是否被 Keil、串口助手或其他程序占用。

### 有 DATA，但样本仍不足

检查 loop 名称、时间戳、数据格式和采样持续时间。先用监视脚本观察原始消息。

### 参数发送后超时

检查设备是否实现协议 v2，返回的 request ID、loop 和参数是否与请求完全一致。
旧格式 ACK 只能被解析，不能确认一次 v2 参数更新。

### 分析拒绝 CSV

错误信息会指出样本数量、NaN、时间戳、采样间隔或 error 字段问题。不要关闭质量门控，
先修正采集或固件遥测。
