"""LLM-based PID tuner.

Builds prompts with control-theory knowledge, sends to DeepSeek API,
parses structured JSON responses, and validates parameter changes
against safety constraints.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from core.analyzer import PerformanceMetrics
from core.config import (
    AppConfig,
    LLMConfig,
    LoopConfig,
    PIDParams,
    TuningConfig,
)
from core.history_manager import TuningHistory

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  System Prompt (injected once per conversation)
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一位经验丰富的PID控制系统调参专家。你的任务是根据系统运行数据和性能指标，\
给出PID参数(Kp, Ki, Kd)的调整建议。

## 调参知识

### 基本规则
1. **超调过大** → 减小Kp 或 增大Kd
2. **响应太慢** → 增大Kp（但注意不要引起振荡）
3. **稳态误差大** → 增大Ki（注意Ki过大会导致积分饱和和振荡）
4. **振荡/抖动** → 减小Kp、增大Kd、或减小Ki
5. **输出饱和** → 整体减小PID增益，考虑加入积分抗饱和

### 调整策略
- 每次只调整1-2个参数，便于观察效果
- 单次调整幅度建议不超过当前值的{max_change_pct}%
- 如果指标已经满足目标要求，不要强行调整
- 关注调参历史，避免参数来回震荡

### 特殊情况
- 如果系统发散（误差持续增大），应大幅减小Kp
- 如果输出持续饱和，说明增益设置过大
- 对于速度环：Ki通常需要较大以消除稳态误差
- 对于位置环：Kd通常需要较大以抑制超调

## 输出格式

你必须严格按照以下JSON格式输出（不要包含任何其他文字）：

```json
{{
  "kp": <float>,
  "ki": <float>,
  "kd": <float>,
  "reason": "<具体分析原因，说明为什么这样调整>",
  "confidence": <0.0-1.0>,
  "expected_improvement": "<预期会改善什么指标>",
  "converged": <true/false, 如果认为当前参数已经足够好则为true>
}}
```

如果认为当前参数已经足够好，设置converged为true，并保持参数不变。
"""


# ──────────────────────────────────────────────
#  User prompt template (each tuning call)
# ──────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """\
## 控制环路: {loop_name} ({loop_description})

## 当前PID参数
Kp = {kp}, Ki = {ki}, Kd = {kd}

## 性能指标（自动计算）
{metrics_text}

## 目标要求
- 最大超调: {target_overshoot}%
- 最大调节时间: {target_settling}s
- 最大稳态误差: {target_sse}%

## 最近采样数据
{data_text}

{history_section}

请分析当前控制性能并给出PID参数调整建议。\
"""


@dataclass(frozen=True)
class TuneResult:
    """Result from a single LLM tuning call."""

    new_params: PIDParams
    reason: str
    confidence: float
    expected_improvement: str
    converged: bool
    model_used: str
    raw_response: str


def build_system_prompt(tuning_config: TuningConfig) -> str:
    """Build the system prompt with current settings."""
    max_change_pct = int(tuning_config.max_change_ratio * 100)
    return SYSTEM_PROMPT.format(max_change_pct=max_change_pct)


def build_user_prompt(
    loop_config: LoopConfig,
    current_pid: PIDParams,
    metrics: PerformanceMetrics,
    data_text: str,
    history: TuningHistory | None = None,
    history_window: int = 5,
) -> str:
    """Build the user prompt for a tuning request."""
    history_section = ""
    if history and history.records:
        history_section = history.generate_summary(max_records=history_window)

    return USER_PROMPT_TEMPLATE.format(
        loop_name=loop_config.name,
        loop_description=loop_config.description,
        kp=current_pid.kp,
        ki=current_pid.ki,
        kd=current_pid.kd,
        metrics_text=metrics.to_prompt_string(),
        target_overshoot=loop_config.target_metrics.max_overshoot_pct,
        target_settling=loop_config.target_metrics.max_settling_time_s,
        target_sse=loop_config.target_metrics.max_sse_pct,
        data_text=data_text,
        history_section=history_section,
    )


@functools.lru_cache(maxsize=4)
def _get_client(api_key: str, base_url: str) -> OpenAI:
    """Cache OpenAI client to reuse connection pool."""
    return OpenAI(api_key=api_key, base_url=base_url)


def call_llm(
    llm_config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    use_fallback: bool = False,
) -> str:
    """Call DeepSeek API and return the raw response text.

    Args:
        llm_config: LLM configuration.
        system_prompt: System-level instructions.
        user_prompt: The current tuning request.
        use_fallback: If True, use fallback model instead of primary.

    Returns:
        Raw response text from the model.
    """
    model = llm_config.model_fallback if use_fallback else llm_config.model

    client = _get_client(llm_config.api_key, llm_config.base_url)

    logger.info("Calling LLM: model=%s", model)

    # DeepSeek-Reasoner (R1) does not support system messages or temperature
    # Use deepseek-chat for system message support
    is_reasoner = "reasoner" in model.lower()

    if is_reasoner:
        # For reasoner model: combine system and user prompts
        combined_prompt = (
            f"[System Instructions]\n{system_prompt}\n\n"
            f"[User Request]\n{user_prompt}"
        )
        messages = [{"role": "user", "content": combined_prompt}]
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=llm_config.max_tokens,
        )
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    content = response.choices[0].message.content or ""
    logger.info("LLM response received (%d chars)", len(content))
    return content


def parse_response(raw_response: str) -> dict[str, Any]:
    """Parse LLM response into a structured dict.

    Handles various response formats:
    - Pure JSON
    - JSON within markdown code blocks
    - JSON with surrounding text
    """
    # Try to extract JSON from markdown code blocks first
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_response, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try to find JSON object by matching outer braces
        start = raw_response.find("{")
        end = raw_response.rfind("}")
        if start != -1 and end > start:
            json_str = raw_response[start:end + 1]
        else:
            raise ValueError(f"No JSON found in response: {raw_response[:200]}")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in response: {e}\nRaw: {json_str[:200]}") from e

    # Validate required fields
    required = {"kp", "ki", "kd"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    return data


def validate_change(
    current: PIDParams,
    proposed: PIDParams,
    tuning_config: TuningConfig,
    loop_config: LoopConfig,
) -> PIDParams:
    """Validate and constrain proposed parameter changes.

    Enforces:
    1. Maximum change ratio per parameter
    2. Safety limits from loop config
    3. Minimum change threshold (treat as no-change if too small)
    """
    max_ratio = tuning_config.max_change_ratio

    def _constrain(current_val: float, proposed_val: float, name: str) -> float:
        if abs(current_val) < 1e-10:
            # For zero-valued params, derive max delta from the loop's limit range
            limit_map = {"Kp": loop_config.limits.kp_max, "Ki": loop_config.limits.ki_max, "Kd": loop_config.limits.kd_max}
            max_delta = limit_map.get(name, 1.0) * max_ratio
        else:
            max_delta = abs(current_val) * max_ratio

        delta = proposed_val - current_val

        if abs(delta) > max_delta:
            constrained = current_val + max_delta * (1 if delta > 0 else -1)
            logger.warning(
                "%s change clamped: %.4f -> %.4f (proposed %.4f, max delta %.4f)",
                name, current_val, constrained, proposed_val, max_delta,
            )
            return constrained

        return proposed_val

    constrained = PIDParams(
        kp=_constrain(current.kp, proposed.kp, "Kp"),
        ki=_constrain(current.ki, proposed.ki, "Ki"),
        kd=_constrain(current.kd, proposed.kd, "Kd"),
    )

    # Apply safety limits
    clamped = loop_config.limits.clamp(constrained)

    return clamped


def tune(
    config: AppConfig,
    loop_name: str,
    current_pid: PIDParams,
    metrics: PerformanceMetrics,
    data_text: str,
    history: TuningHistory | None = None,
) -> TuneResult:
    """Execute a single tuning iteration.

    This is the main entry point for the tuning process:
    1. Build prompts
    2. Call LLM
    3. Parse response
    4. Validate and constrain changes
    5. Return result

    Args:
        config: Application configuration.
        loop_name: Name of the control loop to tune.
        current_pid: Current PID parameters.
        metrics: Current performance metrics.
        data_text: Formatted data sample string.
        history: Optional tuning history for anti-oscillation.

    Returns:
        TuneResult with new parameters and analysis.
    """
    loop_config = config.get_loop(loop_name)

    # Check if already converged
    if metrics.meets_targets(
        loop_config.target_metrics.max_overshoot_pct,
        loop_config.target_metrics.max_settling_time_s,
        loop_config.target_metrics.max_sse_pct,
    ):
        logger.info("Performance already meets targets - checking with LLM anyway")

    system_prompt = build_system_prompt(config.tuning)
    user_prompt = build_user_prompt(
        loop_config=loop_config,
        current_pid=current_pid,
        metrics=metrics,
        data_text=data_text,
        history=history,
        history_window=config.tuning.history_window,
    )

    # Try primary model, fallback on error
    use_fallback = False
    try:
        raw_response = call_llm(
            config.llm, system_prompt, user_prompt, use_fallback=False
        )
    except Exception as e:
        logger.warning("Primary model failed: %s, trying fallback", e)
        use_fallback = True
        raw_response = call_llm(
            config.llm, system_prompt, user_prompt, use_fallback=True
        )

    model_used = (
        config.llm.model_fallback if use_fallback else config.llm.model
    )

    # Parse response
    parsed = parse_response(raw_response)

    proposed = PIDParams(
        kp=float(parsed["kp"]),
        ki=float(parsed["ki"]),
        kd=float(parsed["kd"]),
    )

    converged = parsed.get("converged", False)

    if converged:
        # If converged, keep current params
        new_params = current_pid
        logger.info("LLM reports convergence - keeping current parameters")
    else:
        # Validate and constrain
        new_params = validate_change(
            current=current_pid,
            proposed=proposed,
            tuning_config=config.tuning,
            loop_config=loop_config,
        )

    return TuneResult(
        new_params=new_params,
        reason=parsed.get("reason", "No reason provided"),
        confidence=float(parsed.get("confidence", 0.5)),
        expected_improvement=parsed.get("expected_improvement", ""),
        converged=converged,
        model_used=model_used,
        raw_response=raw_response,
    )
