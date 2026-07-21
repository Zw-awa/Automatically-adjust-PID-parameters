#ifndef PID_TUNER_H
#define PID_TUNER_H

typedef enum
{
    PID_TUNER_OK = 0,
    PID_TUNER_ERROR_CONFIG,
    PID_TUNER_ERROR_PORT
} PIDTuner_Status;

PIDTuner_Status PIDTuner_Init(void);
void PIDTuner_Poll(void);

#endif
