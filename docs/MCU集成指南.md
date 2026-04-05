# PID自动调参系统 - MCU集成指南

## 🎯 概述

本文档指导如何将PID自动调参系统集成到你的MCU（微控制器）项目中。无论你使用Arduino、STM32、ESP32还是其他平台，都可以参考本指南。

## 📋 集成要求

### 硬件要求
- 支持串口通信的MCU开发板
- USB转TTL串口模块（如果需要）
- 你的控制系统（电机、传感器等）

### 软件要求
- MCU开发环境（Arduino IDE、STM32CubeIDE、PlatformIO等）
- 基本的C/C++编程能力
- 了解串口通信原理

## 🔌 通信协议详解

### 协议格式

系统使用简单的文本协议，易于实现和调试：

#### 1. MCU → PC：数据上报
```
DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>\n
```
**示例**：
```
DATA:speed:1.2345,100.0,95.3,-4.7,85.2\n
```

**字段说明**：
- `loop`：控制环名称（speed、steering、position、current）
- `timestamp`：时间戳（秒，浮点数）
- `target`：目标值（你的控制系统期望值）
- `actual`：实际值（传感器测量值）
- `error`：误差值（target - actual）
- `output`：控制器输出值（PID计算的结果）

#### 2. PC → MCU：参数更新
```
PID:<loop>:<Kp>,<Ki>,<Kd>\n
```
**示例**：
```
PID:speed:0.800000,0.150000,0.030000\n
```

#### 3. MCU → PC：确认响应
```
ACK:<loop>:<Kp>,<Ki>,<Kd>\n
```
**示例**：
```
ACK:speed:0.800000,0.150000,0.030000\n
```

#### 4. MCU → PC：信息消息
```
INFO:<message>\n
```
**示例**：
```
INFO:PID parameters updated successfully\n
```

## 🛠️ 集成步骤

### 步骤1：理解参考代码

参考代码 `docs/mcu_reference.c` 提供了完整的协议实现，包含：

1. **数据结构**：PID参数结构体
2. **发送函数**：DATA、INFO消息发送
3. **接收解析**：PID消息解析和验证
4. **安全机制**：参数范围检查

### 步骤2：适配到你的平台

#### Arduino平台适配示例

```cpp
// 基于Arduino的简化实现
#include <Arduino.h>

// PID参数结构
struct PIDParams {
    float kp;
    float ki;
    float kd;
};

PIDParams speed_pid = {1.0, 0.1, 0.05};

void sendData(const char* loop, float timestamp, 
              float target, float actual, float error, float output) {
    Serial.print("DATA:");
    Serial.print(loop);
    Serial.print(":");
    Serial.print(timestamp, 4);
    Serial.print(",");
    Serial.print(target, 3);
    Serial.print(",");
    Serial.print(actual, 3);
    Serial.print(",");
    Serial.print(error, 4);
    Serial.print(",");
    Serial.print(output, 4);
    Serial.println();
}

void setup() {
    Serial.begin(115200);  // 波特率必须和config.json一致
    // 你的其他初始化代码
}

void loop() {
    // 你的控制循环
    float timestamp = millis() / 1000.0;
    float target = 100.0;      // 你的目标值
    float actual = readSensor(); // 读取传感器
    float error = target - actual;
    float output = computePID(error, &speed_pid); // PID计算
    
    // 每秒发送一次数据
    static unsigned long lastSend = 0;
    if (millis() - lastSend > 1000) {
        sendData("speed", timestamp, target, actual, error, output);
        lastSend = millis();
    }
    
    // 检查串口是否有新参数
    checkSerialCommands();
}
```

#### STM32平台适配示例

```c
// 基于STM32 HAL库的实现
#include "main.h"
#include <string.h>
#include <stdio.h>

extern UART_HandleTypeDef huart2;  // 你的串口句柄

PID_Params_t speed_pid = {1.0f, 0.1f, 0.05f};

void send_data(const char* loop_name, float timestamp,
               float target, float actual, float error, float output) {
    char buffer[128];
    int len = snprintf(buffer, sizeof(buffer),
                      "DATA:%s:%.4f,%.3f,%.3f,%.4f,%.4f\n",
                      loop_name, timestamp, target, actual, error, output);
    HAL_UART_Transmit(&huart2, (uint8_t*)buffer, len, 100);
}

// 在串口中断中接收数据
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart->Instance == USART2) {  // 你的串口
        parse_serial_command(rx_buffer);
        // 重新启动接收
        HAL_UART_Receive_IT(&huart2, rx_buffer, 1);
    }
}
```

### 步骤3：实现数据上报

#### 上报频率建议
- **低速系统**（温度控制等）：1-10 Hz
- **中速系统**（电机速度控制）：10-100 Hz
- **高速系统**（无人机姿态）：100-1000 Hz

**重要**：PC端需要足够的数据点进行分析，建议至少每秒10个点。

#### 数据质量要求
1. **时间戳**：使用相对时间或系统时间，保持递增
2. **数值范围**：根据实际系统合理缩放
3. **噪声处理**：适当滤波，但不要过度平滑
4. **异常值**：检测并处理传感器异常

### 步骤4：实现参数接收

#### 解析函数示例
```c
void parse_pid_command(const char* loop, float kp, float ki, float kd) {
    // 1. 验证参数范围
    if (kp < KP_MIN || kp > KP_MAX) {
        send_info("ERROR: Kp out of range");
        return;
    }
    
    // 2. 更新对应环的参数
    if (strcmp(loop, "speed") == 0) {
        speed_pid.kp = kp;
        speed_pid.ki = ki;
        speed_pid.kd = kd;
    } else if (strcmp(loop, "steering") == 0) {
        steer_pid.kp = kp;
        steer_pid.ki = ki;
        steer_pid.kd = kd;
    }
    
    // 3. 发送确认
    send_ack(loop, kp, ki, kd);
    send_info("PID parameters updated");
}
```

### 步骤5：添加安全机制

#### 必须实现的安全检查
1. **参数范围验证**：
   ```c
   #define KP_MIN 0.01f
   #define KP_MAX 50.0f
   // 在接收参数时检查
   ```

2. **变化率限制**（可选但推荐）：
   ```c
   float max_change = current_kp * 0.2f;  // 20%限制
   if (fabs(new_kp - current_kp) > max_change) {
       // 裁剪到允许范围
       new_kp = current_kp + (new_kp > current_kp ? max_change : -max_change);
   }
   ```

3. **异常处理**：
   ```c
   // 检查NaN或无穷大
   if (isnan(kp) || isinf(kp)) {
       send_info("ERROR: Invalid parameter received");
       return;
   }
   ```

## 🔧 调试技巧

### 1. 使用串口监视器
在集成前，先用串口监视器测试：
```bash
# PC端监控串口数据
python scripts/monitor_serial.py COM3
```

### 2. 分阶段测试
1. **阶段1**：只实现数据发送，验证格式正确
2. **阶段2**：添加参数接收，手动发送测试命令
3. **阶段3**：完整集成，运行在线模式测试

### 3. 常见问题排查

#### 问题：PC收不到数据
**检查**：
1. 波特率是否匹配（默认115200）
2. 串口号是否正确
3. 数据格式是否有换行符`\n`
4. 发送频率是否合适

#### 问题：参数更新不生效
**检查**：
1. ACK确认是否发送
2. 参数范围检查是否过严
3. 解析函数是否正确识别环名称

#### 问题：系统不稳定
**检查**：
1. 数据噪声是否过大
2. 发送频率是否过高/过低
3. PID参数是否合理

## 📊 性能优化建议

### 1. 数据上报优化
```c
// 使用静态变量减少重复初始化
void send_data_optimized(...) {
    static char buffer[128];  // 复用缓冲区
    // ... 格式化数据
}
```

### 2. 解析优化
```c
// 使用状态机解析，避免字符串操作
typedef enum {
    STATE_WAITING,
    STATE_IN_COMMAND,
    STATE_IN_LOOP,
    STATE_IN_PARAMS
} ParserState;
```

### 3. 内存优化
- 使用栈分配而非堆分配
- 避免动态内存分配
- 合理设置缓冲区大小

## 🎯 集成示例：直流电机速度控制

### 系统组成
- MCU：Arduino Uno
- 电机：直流有刷电机
- 传感器：编码器（测速）
- 驱动器：L298N电机驱动模块

### 代码框架
```cpp
// Arduino完整示例
#include <Arduino.h>
#include <PID_v1.h>

// PID对象
double setpoint, input, output;
PID myPID(&input, &output, &setpoint, 1.0, 0.1, 0.05, DIRECT);

// 编码器计数
volatile long encoderCount = 0;

void setup() {
    Serial.begin(115200);
    
    // 初始化PID
    myPID.SetMode(AUTOMATIC);
    myPID.SetSampleTime(10);  // 10ms采样
    myPID.SetOutputLimits(-255, 255);
    
    // 初始化编码器中断
    attachInterrupt(digitalPinToInterrupt(2), encoderISR, RISING);
    
    Serial.println("INFO:Motor controller ready");
}

void loop() {
    // 计算速度（RPM）
    static unsigned long lastTime = 0;
    unsigned long now = millis();
    float dt = (now - lastTime) / 1000.0;
    
    if (dt >= 0.1) {  // 每100ms计算一次速度
        float speed_rpm = (encoderCount / 20.0) * (60.0 / dt);  // 假设20脉冲/转
        encoderCount = 0;
        
        // PID计算
        setpoint = 100.0;  // 目标100 RPM
        input = speed_rpm;
        myPID.Compute();
        
        // 设置电机PWM
        analogWrite(9, abs(output));
        digitalWrite(10, output > 0 ? HIGH : LOW);
        
        // 发送数据到PC
        sendData("speed", now/1000.0, setpoint, input, setpoint-input, output);
        
        lastTime = now;
    }
    
    // 检查串口命令
    checkSerial();
}

void encoderISR() {
    encoderCount++;
}
```

## 🔗 与PC端配合

### 配置对应关系
确保MCU和PC端的配置一致：

1. **串口参数**：`config.json`中的`serial.port`和`serial.baudrate`
2. **控制环名称**：MCU发送的`loop`名称必须在`config.json`的`loops`中定义
3. **参数范围**：MCU的检查范围应比PC端略宽，作为最后防线

### 工作流程
1. MCU上电，开始发送数据
2. PC运行在线模式：`python main.py online --port COM3 --loop speed`
3. PC分析数据，给出调参建议
4. 用户确认后，PC发送新参数
5. MCU接收并应用参数，发送ACK确认
6. 重复3-5直到参数收敛

## 🆘 故障排除指南

### 问题矩阵

| 症状 | 可能原因 | 解决方案 |
|------|----------|----------|
| 无数据接收 | 串口未连接/错误 | 检查线缆、端口号、波特率 |
| 数据格式错误 | 缺少换行符/分隔符 | 确保每条消息以`\n`结尾 |
| 参数不更新 | 环名称不匹配 | 检查MCU和PC的环名称是否一致 |
| 系统振荡 | 参数变化太大 | 在MCU端添加变化率限制 |
| 通信中断 | 缓冲区溢出 | 增加PC端`data_buffer_size` |

### 调试命令
```bash
# 1. 测试串口连接
python -m serial.tools.miniterm COM3 115200

# 2. 手动发送PID命令测试
echo "PID:speed:1.0,0.1,0.05" > COM3

# 3. 查看MCU响应
python scripts/monitor_serial.py COM3
```

## 📈 进阶功能

### 1. 多环控制
如果你的系统有多个控制环（如速度+位置），可以：
```c
// 同时管理多个PID环
PID_Params_t pids[MAX_LOOPS];
char* loop_names[MAX_LOOPS] = {"speed", "position"};

// 根据名称选择PID
PID_Params_t* get_pid_by_name(const char* name) {
    for (int i = 0; i < MAX_LOOPS; i++) {
        if (strcmp(loop_names[i], name) == 0) {
            return &pids[i];
        }
    }
    return NULL;
}
```

### 2. 自适应上报频率
根据系统状态动态调整上报频率：
```c
// 稳态时降低频率，瞬态时提高频率
float get_reporting_rate(float error) {
    if (fabs(error) > 10.0) {
        return 100.0;  // 瞬态，100Hz
    } else {
        return 10.0;   // 稳态，10Hz
    }
}
```

### 3. 数据预处理
在MCU端进行简单预处理：
```c
// 移动平均滤波
float filtered_value = moving_average(raw_sensor_value);

// 异常值检测
if (is_outlier(raw_value, history, 3.0)) {  // 3倍标准差
    use_last_valid_value();
}
```

## 🎓 最佳实践总结

1. **从简单开始**：先实现基本功能，再添加高级特性
2. **充分测试**：每个阶段都进行完整测试
3. **添加日志**：使用INFO消息帮助调试
4. **考虑安全**：参数验证是必须的
5. **保持兼容**：遵循协议规范，便于维护

## 📞 获取帮助

如果在集成过程中遇到问题：

1. **查看参考代码**：`docs/mcu_reference.c` 包含完整实现
2. **使用调试工具**：串口监视器是最佳调试工具
3. **简化测试**：先测试最基本的功能
4. **查阅文档**：本文档和`usage.md`包含详细说明
5. **搜索类似问题**：很多问题别人已经遇到过

**祝集成顺利！** 🔧🚀

完成集成后，你就可以享受AI智能调参带来的便利了！