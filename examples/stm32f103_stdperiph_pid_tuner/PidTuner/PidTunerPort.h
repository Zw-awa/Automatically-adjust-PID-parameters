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

/* 在已有中断函数中转发给这两个函数，不要把协议解析放进中断。 */
void PIDTuner_PortTick1ms(void);
void PIDTuner_PortOnUsart1Irq(void);

#endif
