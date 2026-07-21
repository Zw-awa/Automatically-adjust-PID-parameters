#ifndef PID_TUNER_USER_H
#define PID_TUNER_USER_H

float PIDTuner_UserReadTarget(void);
float PIDTuner_UserReadActual(void);
void PIDTuner_UserWriteOutput(float output, float dt_seconds);

#endif
