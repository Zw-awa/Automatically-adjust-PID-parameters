# MCU 集成指南

这份文档面向已经有自己设备的人，目标只有一个：让你的 MCU 能和 PC 端在线调参流程正常配合。

## 1. 先明确你要做到什么

如果你想用在线模式，MCU 至少要能做两件事：

1. 周期性把当前控制数据发给 PC
2. 接收 PC 发来的新 PID 参数并应用

你不需要完全照搬别人的工程，只需要把协议对上。

## 2. PC 端希望收到什么

### 数据上报格式

```text
DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>\n
```

示例：

```text
DATA:speed:1.2345,100.0,95.3,-4.7,85.2\n
```

这几个值分别代表：

1. `loop`
控制环名字，比如 `speed`
2. `timestamp`
时间戳，单位秒
3. `target`
目标值
4. `actual`
实际值
5. `error`
误差
6. `output`
控制器输出

### 参数下发格式

```text
PID:<loop>:<Kp>,<Ki>,<Kd>\n
```

示例：

```text
PID:speed:0.800000,0.150000,0.030000\n
```

### 确认返回格式

```text
ACK:<loop>:<Kp>,<Ki>,<Kd>\n
```

示例：

```text
ACK:speed:0.800000,0.150000,0.030000\n
```

## 3. 为什么推荐 STM32 先按参考文件改

因为你第一次接入时，最容易卡的不是 PID 算法本身，而是：

1. 串口行格式不对
2. 没有换行
3. 环名字不一致
4. 收到参数后没有返回 ACK

所以最省时间的办法通常是：

1. 先用 `mcu_reference.c` 把协议打通
2. 再把里面的目标值、实际值和控制器逻辑替换成你自己的

## 4. 对 STM32 来说你最常改的地方

在 `mcu_reference.c` 里，你通常会改这几块：

1. `PID_TUNER_UART_HANDLE`
改成你实际使用的串口句柄
2. `PID_TUNER_UART_TX_GPIO_PORT` 和 `PID_TUNER_UART_TX_PIN`
改成你实际使用的 TX 引脚
3. `PID_TUNER_UART_RX_GPIO_PORT` 和 `PID_TUNER_UART_RX_PIN`
改成你实际使用的 RX 引脚
4. `PID_TUNER_LOOP_NAME`
改成你真正要调的控制环名字
5. `App_GetSpeedTarget()`
改成你自己的目标值来源
6. `App_GetSpeedActual()`
改成你自己的测量值来源
7. `App_ComputeSpeedOutput()`
改成你真实使用的 PID 控制器逻辑

## 5. 建议你怎么联调

### 第一步：先只看串口有没有数据

```bash
python scripts/monitor_serial.py --port COM3
```

这里的 `COM3` 只是默认示例，运行前改成你电脑上的实际串口。

先确认：

1. 串口能打开
2. 设备确实在发
3. 消息格式是 `DATA:...`

### 第二步：先采一份数据

```bash
python scripts/collect_data.py --port COM3 --loop speed --duration 20
```

这里的 `COM3` 只是默认示例，运行前改成你电脑上的实际串口。

先确认：

1. `loop` 名字匹配
2. 数据量够
3. CSV 已经正常保存

### 第三步：先离线分析

把 `--file` 换成你刚采集出来的 CSV 文件路径。

先看：

1. 指标是不是合理
2. 模型建议是不是方向正常

### 第四步：最后再在线调参

```bash
python main.py online --port COM3 --loop speed --interval 10
```

这里的 `COM3` 只是默认示例，运行前改成你电脑上的实际串口。

## 6. 你最容易忽略的几个点

### 6.1 换行

每条串口消息都要以换行结尾，不然 PC 端很难按行解析。

### 6.2 环名字

如果 MCU 发的是：

```text
DATA:speed:...
```

那你本地配置里也必须有 `speed` 这个环。

### 6.3 ACK

PC 端在线模式在发出新 PID 后，会等待 ACK。

如果你 MCU 应用了新参数却不回 ACK，PC 端会认为没有确认。

### 6.4 参数保护

即使 PC 端已经做了限制，MCU 端仍然建议保留：

1. 上下限检查
2. `NaN / inf` 检查
3. 必要时变化率限制

## 7. 如果你是第一次接真实设备

最稳的顺序还是这四步：

1. `monitor_serial.py`
2. `collect_data.py`
3. `offline`
4. `online`

先证明数据能进来，再证明建议看起来合理，最后再开始实时回写参数。
