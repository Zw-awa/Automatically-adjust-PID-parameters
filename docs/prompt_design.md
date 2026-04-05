# PID自动调参系统 - 提示词设计指南

## 🎯 提示词设计理念

本系统的核心创新在于使用LLM进行PID参数调优。精心设计的提示词是确保LLM理解控制工程上下文、提供专业建议的关键。

### 设计原则

1. **专业性**：让LLM扮演控制系统专家角色
2. **结构化**：提供清晰的上下文和约束条件
3. **可解析性**：确保响应格式便于程序提取
4. **安全性**：包含参数限制和安全约束
5. **可解释性**：要求LLM提供调参理由和置信度

## 📋 提示词模板详解

### 完整模板

```text
你是一个专业的控制系统工程师，擅长PID参数整定。请基于以下系统信息和性能数据，给出PID参数调整建议。

【系统信息】
控制环：{loop_name} ({loop_description})
当前参数：Kp={current_kp:.6f}, Ki={current_ki:.6f}, Kd={current_kd:.6f}
参数限制：Kp∈[{kp_min:.6f},{kp_max:.6f}], Ki∈[{ki_min:.6f},{ki_max:.6f}], Kd∈[{kd_min:.6f},{kd_max:.6f}]
最大变化率：{max_change_ratio:.0%}（单次调参）

【性能指标】
超调量：{overshoot_pct:.1f}% (目标：<{target_overshoot:.1f}%)
调节时间：{settling_time_s:.3f}s (目标：<{target_settling_time:.1f}s)
稳态误差：{sse_pct:.1f}% (目标：<{target_sse:.1f}%)
振荡次数：{oscillation_count}次

【最近数据样本（时间戳,目标值,实际值,误差,输出）】
{data_samples}

【调参历史（最近{history_count}次）】
{history_summary}

【调参目标】
1. 首要目标：{primary_goal}
2. 次要目标：{secondary_goal}
3. 约束条件：参数变化不超过{max_change_ratio:.0%}，且必须在上述限制范围内

【输出格式要求】
请严格按照以下格式回复：
新参数：Kp={new_kp:.6f}, Ki={new_ki:.6f}, Kd={new_kd:.6f}
理由：{reason}
置信度：{confidence}%
预期改进：{expected_improvement}

【注意事项】
1. 如果当前性能已满足所有目标，请回复"已收敛"，无需调整参数
2. 如果数据质量差或噪声大，建议保守调整
3. 考虑参数间的耦合关系（如Kp和Kd的平衡）
4. 优先解决最严重的性能问题
```

### 各部分详解

#### 1. 角色设定
```text
你是一个专业的控制系统工程师，擅长PID参数整定。
```
**作用**：让LLM进入专家角色，使用专业术语和思维

#### 2. 系统信息
```text
控制环：速度环（电机速度控制）
当前参数：Kp=1.000000, Ki=0.100000, Kd=0.050000
参数限制：Kp∈[0.010000,50.000000], Ki∈[0.000000,20.000000], Kd∈[0.000000,10.000000]
最大变化率：20%（单次调参）
```
**作用**：
- 提供完整的系统上下文
- 设置安全边界（参数限制）
- 防止剧烈变化（变化率限制）

#### 3. 性能指标
```text
超调量：15.2% (目标：<5.0%)
调节时间：0.420s (目标：<0.5s)
稳态误差：0.8% (目标：<1.0%)
振荡次数：2次
```
**作用**：
- 量化当前性能问题
- 提供明确的改进目标
- 帮助LLM确定调参优先级

#### 4. 数据样本
```text
0.000,100.000,0.000,100.000,500.000
0.010,100.000,4.850,95.150,480.750
0.020,100.000,9.420,90.580,462.900
...
```
**作用**：
- 提供原始数据供LLM分析
- 限制数据量（通常50-100个点）
- 标准化格式便于解析

#### 5. 调参历史
```text
迭代1：Kp=1.200→1.000 (-16.7%)，超调量25%→15%
迭代2：Kp=1.000→0.800 (-20.0%)，超调量15%→10%
```
**作用**：
- 提供调参趋势信息
- 避免重复无效调整
- 检测参数振荡

#### 6. 输出格式
```text
新参数：Kp=0.800000, Ki=0.150000, Kd=0.030000
理由：超调量仍然偏高，减小Kp可以降低系统增益，增加Ki可以改善稳态误差
置信度：85%
预期改进：超调量预计降至8-10%，稳态误差降至0.5%
```
**作用**：
- 确保响应可被程序解析
- 提供调参理由供用户理解
- 量化调参预期效果

## 🔧 提示词变体

### 针对不同问题的提示词调整

#### 1. 高超调量问题
```text
【调参目标】
1. 首要目标：显著降低超调量（当前{overshoot_pct:.1f}%，目标<{target_overshoot:.1f}%）
2. 次要目标：保持调节时间基本不变
3. 建议策略：适当减小Kp，可能增加Kd来抑制振荡
```

#### 2. 调节时间过长
```text
【调参目标】
1. 首要目标：缩短调节时间（当前{settling_time_s:.3f}s，目标<{target_settling_time:.1f}s）
2. 次要目标：控制超调量在可接受范围
3. 建议策略：适当增加Kp，调整Ki/Kd平衡
```

#### 3. 稳态误差过大
```text
【调参目标】
1. 首要目标：减小稳态误差（当前{sse_pct:.1f}%，目标<{target_sse:.1f}%）
2. 次要目标：避免引入振荡
3. 建议策略：适当增加Ki，微调Kp
```

#### 4. 系统振荡
```text
【调参目标】
1. 首要目标：消除振荡（当前{oscillation_count}次振荡）
2. 次要目标：保持响应速度
3. 建议策略：增加Kd（微分作用），可能减小Kp
```

### 针对不同控制环的调整

#### 速度环（快速响应）
```text
【系统特性】
- 需要快速响应速度变化
- 允许适度超调（<10%）
- 稳态误差要求中等（<2%）
```

#### 位置环（高精度）
```text
【系统特性】
- 需要高精度位置控制
- 超调量要求严格（<2%）
- 稳态误差要求高（<0.5%）
- 可以接受较长的调节时间
```

#### 电流环（快速稳定）
```text
【系统特性】
- 需要快速稳定电流
- 超调量要求中等（<5%）
- 调节时间要求严格（<0.1s）
- 抗干扰能力重要
```

## 🧪 提示词测试和优化

### 测试用例设计

#### 用例1：理想响应
```python
# 输入：性能良好，接近目标
metrics = {
    "overshoot_pct": 3.2,
    "settling_time_s": 0.35,
    "sse_pct": 0.5,
    "oscillation_count": 0
}
# 期望输出："已收敛"或微小调整
```

#### 用例2：严重超调
```python
# 输入：超调量很大
metrics = {
    "overshoot_pct": 25.0,  # 严重超调
    "settling_time_s": 0.8,
    "sse_pct": 1.2,
    "oscillation_count": 3
}
# 期望输出：显著减小Kp，可能增加Kd
```

#### 用例3：稳态误差大
```python
# 输入：稳态误差大
metrics = {
    "overshoot_pct": 5.0,
    "settling_time_s": 0.4,
    "sse_pct": 5.0,  # 稳态误差大
    "oscillation_count": 0
}
# 期望输出：增加Ki
```

### 优化策略

#### 1. 添加工程经验规则
```text
【工程经验】
- 超调量>20%：优先减小Kp
- 稳态误差>3%：优先增加Ki  
- 振荡次数>3：优先增加Kd
- 调节时间>2倍目标：适当增加Kp
```

#### 2. 提供调参策略选项
```text
【可选策略】
A. 保守策略：小幅度调整（<10%），多次迭代
B. 激进策略：较大幅度调整（<20%），快速收敛
C. 平衡策略：综合考虑所有指标

请根据当前情况选择最合适的策略。
```

#### 3. 添加物理约束
```text
【物理约束】
- 执行器饱和限制：输出范围[-1000, 1000]
- 采样频率：100Hz
- 系统延迟：约0.02s
- 测量噪声：标准差约0.5
```

## 🔍 响应解析和处理

### 解析逻辑

```python
def parse_llm_response(response: str) -> Optional[TuneResult]:
    """解析LLM响应，提取调参建议"""
    
    # 检查是否收敛
    if "已收敛" in response or "converged" in response.lower():
        return TuneResult(converged=True)
    
    # 正则表达式提取参数
    param_pattern = r"Kp=([\d\.]+),\s*Ki=([\d\.]+),\s*Kd=([\d\.]+)"
    reason_pattern = r"理由：(.+?)(?=\n|置信度|$)"
    confidence_pattern = r"置信度：([\d\.]+)%"
    
    # 提取和验证
    params = extract_and_validate(params_match)
    reason = extract_reason(reason_match)
    confidence = extract_confidence(confidence_match)
    
    return TuneResult(
        new_params=params,
        reason=reason,
        confidence=confidence,
        converged=False
    )
```

### 错误处理

#### 1. 格式错误
```python
if not params_match:
    logger.warning("LLM响应格式错误，未找到参数")
    # 尝试启发式提取
    params = heuristic_extract(response)
    if params:
        return TuneResult(params, "格式解析失败，使用启发式提取", 50.0)
    else:
        raise ParseError("无法解析LLM响应")
```

#### 2. 参数越界
```python
if not within_limits(params, config):
    logger.warning("LLM建议参数越界，进行裁剪")
    params = clip_to_limits(params, config)
    reason = f"原建议越界，已裁剪到限制范围内。{reason}"
    confidence = confidence * 0.8  # 降低置信度
```

#### 3. 变化率过大
```python
if change_too_large(params, current_params, config):
    logger.warning("变化率过大，进行限制")
    params = limit_change_rate(params, current_params, config)
    reason = f"变化率超过{config.max_change_ratio:.0%}限制，已调整。{reason}"
```

## 📊 提示词效果评估

### 评估指标

1. **建议质量**：调参后实际性能改善程度
2. **安全性**：参数是否在合理范围内
3. **可解析性**：响应格式正确率
4. **解释性**：理由的清晰度和相关性
5. **收敛速度**：达到目标性能所需的迭代次数

### A/B测试设计

```python
# 测试不同提示词版本的效果
prompt_versions = [
    ("基础版", base_prompt_template),
    ("详细版", detailed_prompt_template),
    ("专家版", expert_prompt_template),
]

for version_name, template in prompt_versions:
    results = test_prompt(template, test_cases)
    print(f"{version_name}: 成功率={results.success_rate:.1%}")
```

## 🚀 最佳实践

### 1. 保持上下文简洁
- 提供必要信息，避免信息过载
- 使用清晰的结构和标题
- 限制数据样本数量（50-100点足够）

### 2. 明确约束条件
- 参数范围限制必须明确
- 变化率限制要突出显示
- 物理约束要具体

### 3. 要求结构化输出
- 强制要求特定格式
- 包含所有必要字段
- 便于程序自动化处理

### 4. 提供调参理由
- 要求LLM解释调参逻辑
- 帮助用户理解决策过程
- 便于后续分析和优化

### 5. 测试和迭代
- 设计全面的测试用例
- 收集实际使用反馈
- 持续优化提示词模板

## 💡 高级技巧

### 1. 上下文学习（Few-shot Learning）
```text
【示例1】
问题：超调量20%，调节时间0.6s
建议：Kp=0.7, Ki=0.12, Kd=0.04
理由：减小Kp降低增益，增加Ki改善稳态性能

【示例2】
问题：稳态误差3%，无超调
建议：Kp=1.0, Ki=0.2, Kd=0.05
理由：增加Ki减小稳态误差，保持Kp稳定响应

【当前问题】
...
```

### 2. 思维链（Chain-of-Thought）
```text
请按以下步骤思考：
1. 分析当前主要性能问题是什么
2. 确定需要调整哪个参数最有效
3. 考虑参数间的耦合影响
4. 确定调整幅度
5. 验证调整后的预期效果
```

### 3. 多角度分析
```text
请从以下角度分析：
- 稳定性角度：系统是否稳定？有无振荡？
- 响应速度角度：调节时间是否合适？
- 精度角度：稳态误差是否满足要求？
- 鲁棒性角度：参数是否过于敏感？
```

## 📈 持续改进

### 收集反馈数据
```python
# 记录每次调参的输入和输出
feedback_data = {
    "input": {
        "metrics": current_metrics,
        "params": current_params,
        "prompt_version": prompt_version
    },
    "output": {
        "suggestion": llm_suggestion,
        "actual_improvement": actual_improvement,
        "user_feedback": user_rating
    }
}
```

### 分析改进机会
1. **成功率分析**：哪些情况下提示词效果不好？
2. **模式识别**：LLM是否有系统性偏差？
3. **用户反馈**：用户对调参理由的理解程度？
4. **性能对比**：不同提示词版本的相对效果？

### 迭代优化流程
```
收集数据 → 分析问题 → 设计改进 → A/B测试 → 部署优化
    ↑                                      ↓
    └──────────────────────────────────────┘
```

## 🎯 总结

优秀的提示词设计是LLM在专业领域成功应用的关键。对于PID自动调参系统，提示词需要：

1. **建立专业上下文**：让LLM成为控制系统专家
2. **提供完整信息**：系统参数、性能数据、历史记录
3. **设置明确约束**：安全边界和变化限制
4. **要求结构化输出**：便于自动化处理
5. **鼓励解释性思考**：提供调参理由和置信度

通过持续测试和优化，可以不断提升提示词的效果，使LLM成为真正有用的PID调参助手。