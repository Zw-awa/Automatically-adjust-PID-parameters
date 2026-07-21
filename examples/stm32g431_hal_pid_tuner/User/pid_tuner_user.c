#include "pid_tuner_user.h"

#include "pid_tuner_config.h"

/* 接真实小车时，主要修改本文件中的三个公开函数。 */
static float g_demo_actual;

float PIDTuner_UserReadTarget(void)
{
#if PID_TUNER_USE_SOFTWARE_PLANT
    return PID_TUNER_DEMO_TARGET;
#else
    /* 实机示例：return Speed_GetTargetRpm(); */
    return 0.0f;
#endif
}

float PIDTuner_UserReadActual(void)
{
#if PID_TUNER_USE_SOFTWARE_PLANT
    return g_demo_actual;
#else
    /* 实机示例：return Encoder_GetSpeedRpm(); */
    return 0.0f;
#endif
}

void PIDTuner_UserWriteOutput(float output, float dt_seconds)
{
#if PID_TUNER_USE_SOFTWARE_PLANT
    /* 软件对象不会操作 PWM；这里只用于验证通信和调参流程。 */
    g_demo_actual += ((output - g_demo_actual) / PID_TUNER_DEMO_PLANT_TAU_S)
        * dt_seconds;
#else
    /* 实机示例：Motor_SetPwm((int16_t)output); */
    (void)output;
    (void)dt_seconds;
#endif
}
