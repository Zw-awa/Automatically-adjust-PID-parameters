#ifndef PID_TUNER_H
#define PID_TUNER_H

typedef enum
{
    PID_TUNER_OK = 0,
    PID_TUNER_ERROR_CONFIG,
    PID_TUNER_ERROR_PORT
} PIDTuner_Status;

/* 必须在时钟初始化完成后调用一次。 */
PIDTuner_Status PIDTuner_Init(void);

/* 必须放在 while (1) 中持续调用，不能放入中断。 */
void PIDTuner_Poll(void);

#endif
