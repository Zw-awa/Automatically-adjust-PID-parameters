# PID自动调参系统 - 架构设计

## 🏗️ 系统架构概述

本系统采用模块化设计，核心思想是将传统的PID调参过程与LLM智能分析相结合。系统架构分为三个层次：数据层、业务层、接口层。

```
┌─────────────────────────────────────────────────┐
│                   用户接口层                      │
├─────────────────────────────────────────────────┤
│ 命令行接口(CLI) │ 批处理脚本 │ 可视化工具 │ 串口监控 │
└─────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────┐
│                   业务逻辑层                      │
├─────────────────────────────────────────────────┤
│   调参引擎   │ 数据分析器 │ 历史管理器 │ 配置管理   │
│   (LLM集成)  │           │           │           │
└─────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────┐
│                   数据访问层                      │
├─────────────────────────────────────────────────┤
│  串口通信   │ 文件I/O   │ 网络API   │ 数据缓存    │
└─────────────────────────────────────────────────┘
```

## 📦 核心模块详解

### 1. 调参引擎 (`core/tuner.py`)

**职责**：与LLM交互，生成PID参数调整建议

**核心流程**：
1. 接收当前PID参数和性能数据
2. 构建LLM提示词（包含系统上下文、历史、目标）
3. 调用DeepSeek API获取建议
4. 解析LLM响应，提取新参数
5. 验证参数合法性（范围、变化率等）

**关键技术**：
- 提示词工程：精心设计的提示词模板
- 响应解析：正则表达式提取结构化数据
- 错误处理：API失败时的降级策略

### 2. 串口管理器 (`core/serial_manager.py`)

**职责**：管理与MCU的串口通信

**功能特性**：
- 异步数据读取（不阻塞主线程）
- 协议解析（DATA/PID/ACK消息）
- 超时重试机制
- 连接状态监控

**通信协议**：
```python
# 数据上报
"DATA:speed:1.2345,100.0,95.3,-4.7,85.2\n"

# 参数更新  
"PID:speed:0.800000,0.150000,0.030000\n"

# 确认响应
"ACK:speed:0.800000,0.150000,0.030000\n"
```

### 3. 数据收集器 (`core/data_collector.py`)

**职责**：缓存和处理实时数据

**数据结构**：
```python
@DataClass
class DataSample:
    timestamp: float    # 时间戳（秒）
    target: float      # 目标值
    actual: float      # 实际值
    error: float       # 误差值
    output: float      # 控制器输出
```

**功能**：
- 环形缓冲区管理（固定大小）
- 数据过滤和清洗
- 实时记录到CSV文件
- 按时间窗口提取数据

### 4. 性能分析器 (`core/analyzer.py`)

**职责**：计算控制系统性能指标

**分析的指标**：
1. **超调量 (Overshoot)**
   - 计算公式：`max(actual - target) / target * 100%`
   - 反映系统的稳定性

2. **调节时间 (Settling Time)**
   - 进入±2%误差带所需时间
   - 反映系统的响应速度

3. **稳态误差 (Steady-State Error)**
   - 稳定后的平均误差
   - 反映系统的精度

4. **振荡次数 (Oscillations)**
   - 响应曲线穿越目标值的次数
   - 反映系统的阻尼特性

### 5. 历史管理器 (`core/history_manager.py`)

**职责**：记录和追踪调参过程

**数据结构**：
```python
@DataClass
class TuningRecord:
    timestamp: datetime      # 调参时间
    iteration: int          # 迭代次数
    pid_before: Dict        # 调参前的参数
    pid_after: Dict         # 调参后的参数
    metrics: Dict           # 性能指标
    reason: str            # LLM调参理由
    confidence: float      # LLM置信度
```

**功能**：
- 收敛检测（连续N次无显著改进）
- 振荡检测（参数来回变化）
- 趋势分析（参数变化方向）
- 持久化存储（JSON格式）

### 6. 配置管理 (`core/config.py`)

**职责**：管理系统配置和参数验证

**配置结构**：
```python
@DataClass
class AppConfig:
    serial: SerialConfig      # 串口配置
    llm: LLMConfig           # LLM API配置
    loops: Dict[str, LoopConfig]  # 控制环配置
    tuning: TuningConfig     # 调参参数
    online: OnlineConfig     # 在线模式配置
```

**验证机制**：
- 类型检查（Pydantic模型）
- 范围验证（参数上下限）
- 依赖检查（配置项间关系）
- 默认值填充（缺失配置）

## 🔄 数据流设计

### 在线模式数据流

```
MCU设备 → 串口数据 → 数据收集器 → 性能分析器 → 调参引擎 → LLM API
    ↑                                      ↓              ↓
    └─────── 串口管理器 ←─────── 参数验证 ←─────── 响应解析
```

**时序说明**：
1. MCU每秒发送10-100个数据点
2. 数据收集器缓存最近N个点（默认200）
3. 每10秒触发一次分析
4. 分析器计算性能指标
5. 调参引擎构建提示词并调用LLM
6. 解析LLM响应，验证参数
7. 通过串口发送新参数（需用户确认）
8. MCU确认接收，更新参数

### 离线模式数据流

```
CSV文件 → 数据解析 → 性能分析器 → 调参引擎 → LLM API
                              ↓              ↓
                        参数验证 ←─────── 响应解析
```

### 仿真模式数据流

```
软件模型 → 生成数据 → 性能分析器 → 调参引擎 → LLM API
    ↑                        ↓              ↓
    └─────── 更新参数 ←─────── 参数验证 ←─────── 响应解析
```

## 🧠 LLM集成设计

### 提示词模板

系统使用结构化提示词确保LLM理解控制工程上下文：

```
你是一个专业的控制系统工程师，擅长PID参数整定。

系统信息：
- 控制环：{loop_name} ({loop_description})
- 当前参数：Kp={kp}, Ki={ki}, Kd={kd}
- 参数限制：Kp∈[{kp_min},{kp_max}], Ki∈[{ki_min},{ki_max}], Kd∈[{kd_min},{kd_max}]

性能数据：
{performance_metrics}

最近数据样本（时间戳,目标值,实际值,误差,输出）：
{data_samples}

调参历史（最近{history_count}次）：
{tuning_history}

调参目标：
1. 超调量 < {max_overshoot}%
2. 调节时间 < {max_settling_time}s  
3. 稳态误差 < {max_sse}%

请分析当前性能，给出新的PID参数建议。
格式必须严格遵循：
新参数：Kp={new_kp}, Ki={new_ki}, Kd={new_kd}
理由：{reason}
置信度：{confidence}%
预期改进：{expected_improvement}
```

### 响应解析

使用正则表达式提取结构化信息：

```python
# 匹配新参数
pattern = r"Kp=([\d\.]+),\s*Ki=([\d\.]+),\s*Kd=([\d\.]+)"
# 匹配理由
pattern = r"理由：(.+)"
# 匹配置信度  
pattern = r"置信度：([\d\.]+)%"
```

### 错误处理策略

1. **API失败**：降级到备用模型（reasoner → chat）
2. **解析失败**：重试或使用保守调整
3. **网络超时**：增加超时时间，最多重试3次
4. **无效响应**：使用历史趋势进行保守调整

## 🗃️ 数据存储设计

### 文件结构

```
data/
├── raw/              # 原始数据
│   ├── 2024-01-15_speed.csv
│   └── 2024-01-15_steering.csv
├── processed/        # 处理后的数据
│   ├── metrics/
│   └── features/
└── logs/            # 系统日志
    ├── tuner.log
    └── serial.log

outputs/
├── figures/         # 生成的图表
│   ├── response_curves/
│   └── tuning_history/
└── reports/         # 调参报告
    ├── 2024-01-15_speed.json
    └── 2024-01-15_steering.json
```

### 数据格式

**CSV数据文件**：
```csv
timestamp,target,actual,error,output
0.0000,100.0,0.0,100.0,500.0
0.0100,100.0,4.85,95.15,480.75
0.0200,100.0,9.42,90.58,462.9
```

**调参历史文件**：
```json
{
  "loop_name": "speed",
  "records": [
    {
      "timestamp": "2024-01-15T10:30:00",
      "iteration": 1,
      "pid_before": {"kp": 1.0, "ki": 0.1, "kd": 0.05},
      "pid_after": {"kp": 0.8, "ki": 0.15, "kd": 0.03},
      "metrics": {
        "overshoot_pct": 15.2,
        "settling_time_s": 0.42,
        "sse_pct": 0.8
      },
      "reason": "超调量偏高，建议减小Kp增加阻尼",
      "confidence": 85.0,
      "model_used": "deepseek-reasoner"
    }
  ]
}
```

## 🔒 安全机制设计

### 多层保护策略

1. **参数范围限制**（配置驱动）
   ```python
   if new_kp < config.loops[loop_name].limits.kp[0]:
       new_kp = config.loops[loop_name].limits.kp[0]
   ```

2. **变化率限制**（防止剧烈变化）
   ```python
   max_change = current_value * config.tuning.max_change_ratio
   new_value = clamp(new_value, 
                     current_value - max_change, 
                     current_value + max_change)
   ```

3. **收敛检测**（避免过度调参）
   ```python
   if consecutive_converged >= config.tuning.convergence_patience:
       stop_tuning()
   ```

4. **手动确认**（用户控制权）
   ```python
   if not config.online.auto_apply:
       user_confirmation = ask_user("Apply new parameters?")
   ```

5. **MCU端验证**（双重检查）
   ```c
   // MCU参考代码中的保护
   if (kp < KP_MIN || kp > KP_MAX) return ERROR;
   ```

### 异常处理

系统设计了完整的异常处理链：

```python
try:
    # 主要业务逻辑
    result = tune(config, ...)
except LLMError as e:
    logger.error(f"LLM调用失败: {e}")
    fallback_to_conservative_tuning()
except SerialError as e:
    logger.error(f"串口通信失败: {e}")
    retry_or_abort()
except ValidationError as e:
    logger.error(f"参数验证失败: {e}")
    use_last_valid_params()
except Exception as e:
    logger.critical(f"未预期错误: {e}")
    graceful_shutdown()
```

## ⚡ 性能优化

### 实时性保障

1. **数据缓冲**：环形缓冲区避免内存增长
2. **异步处理**：串口读取不阻塞主线程
3. **批量分析**：定时触发而非逐点分析
4. **缓存机制**：频繁访问的数据缓存

### 资源管理

1. **连接池**：串口连接复用
2. **内存监控**：大数据集时警告
3. **文件句柄**：及时关闭文件
4. **网络连接**：超时和重连机制

## 🔧 扩展性设计

### 添加新的控制环

1. 在 `config.json` 中添加环配置
2. （可选）实现环特定的分析逻辑
3. 更新文档和示例

### 集成其他LLM提供商

1. 实现新的LLM适配器
2. 更新配置结构
3. 修改提示词模板

### 添加新的数据源

1. 实现新的数据收集器
2. 适配数据格式
3. 更新数据流配置

## 🧪 测试策略

### 单元测试
- 每个核心模块独立的测试
- 模拟LLM响应测试解析逻辑
- 边界条件测试（参数范围）

### 集成测试
- 完整工作流测试（数据→分析→调参）
- 串口通信模拟测试
- 错误处理流程测试

### 系统测试
- 仿真模式端到端测试
- 性能基准测试
- 长时间运行稳定性测试

## 📈 监控和日志

### 日志级别
- DEBUG：详细调试信息
- INFO：正常操作记录
- WARNING：潜在问题警告
- ERROR：错误信息
- CRITICAL：严重故障

### 监控指标
- 调参迭代次数
- LLM调用成功率
- 平均响应时间
- 参数收敛趋势
- 系统资源使用

---

## 🎯 设计原则总结

1. **模块化**：每个模块职责单一，接口清晰
2. **可配置**：通过配置文件控制行为，无需修改代码
3. **安全性**：多层保护机制，防止参数失控
4. **容错性**：完善的错误处理和降级策略
5. **可扩展**：易于添加新功能和控制环
6. **用户友好**：清晰的文档和交互界面

这个架构设计平衡了功能性、安全性和易用性，为PID自动调参提供了一个可靠的基础平台。