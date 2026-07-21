#ifndef PID_TUNER_CONFIG_H
#define PID_TUNER_CONFIG_H

/* ===== 初次移植时主要检查和修改这一段 ===== */
#define PID_TUNER_LOOP_NAME              "speed"
#define PID_TUNER_CONTROL_PERIOD_MS      10U
#define PID_TUNER_TELEMETRY_PERIOD_MS    50U

#define PID_TUNER_INITIAL_KP             1.0f
#define PID_TUNER_INITIAL_KI             0.1f
#define PID_TUNER_INITIAL_KD             0.05f

#define PID_TUNER_KP_MIN                 0.01f
#define PID_TUNER_KP_MAX                 50.0f
#define PID_TUNER_KI_MIN                 0.0f
#define PID_TUNER_KI_MAX                 20.0f
#define PID_TUNER_KD_MIN                 0.0f
#define PID_TUNER_KD_MAX                 10.0f
#define PID_TUNER_OUTPUT_MIN             (-100.0f)
#define PID_TUNER_OUTPUT_MAX             100.0f

/* 1：板内软件对象；0：在 pid_tuner_user.c 中接真实传感器和执行器。 */
#define PID_TUNER_USE_SOFTWARE_PLANT     1U
#define PID_TUNER_DEMO_TARGET            50.0f
#define PID_TUNER_DEMO_PLANT_TAU_S       0.25f

/* ===== 协议和缓冲区参数，通常不需要修改 ===== */
#define PID_TUNER_RX_SIZE                128U
#define PID_TUNER_TX_SIZE                512U
#define PID_TUNER_FORMAT_LINE_SIZE       160U
#define PID_TUNER_REQUEST_ID_SIZE        13U
#define PID_TUNER_UPDATE_MAX_AGE_MS      3000U
#define PID_TUNER_D_FILTER_TAU_S         0.01f

#endif
