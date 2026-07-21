#ifndef PID_TUNER_PORT_H
#define PID_TUNER_PORT_H

#include <stdint.h>

typedef enum
{
    PID_TUNER_PORT_LINE_NONE = 0,
    PID_TUNER_PORT_LINE_READY,
    PID_TUNER_PORT_LINE_OVERFLOW
} PIDTuner_PortLineStatus;

uint8_t PIDTuner_PortInit(void);
void PIDTuner_PortPoll(void);
uint32_t PIDTuner_PortMillis(void);
uint8_t PIDTuner_PortWrite(const char *text);
PIDTuner_PortLineStatus PIDTuner_PortReadLine(char *line, uint16_t size);

/* 已有 HAL 回调时，只需在原回调中调用对应函数。 */
void PIDTuner_PortOnRxComplete(void);
void PIDTuner_PortOnTxComplete(void);
void PIDTuner_PortOnError(void);

#endif
