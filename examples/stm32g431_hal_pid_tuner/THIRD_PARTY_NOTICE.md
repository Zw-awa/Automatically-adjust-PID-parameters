# 第三方代码说明

本 demo 的 `User/pid_tuner.*`、精简后的 `Core/Src/main.c` 和中文文档为本项目
新增内容，按仓库的 MIT License 发布。

`Drivers/STM32G4xx_HAL_Driver/`、`Drivers/CMSIS/Device/ST/` 和启动文件来自
STMicroelectronics，保留其 BSD-3-Clause 条款；`Drivers/CMSIS/Include/` 来自
Arm，保留 Apache-2.0 条款。

其余 `Core/` 文件由参考工程中的 STM32CubeMX 生成。文件头引用的组件根目录
`LICENSE` 未随参考工程提供，因此本仓库只保留其原始 AS-IS 声明，不将这些
文件重新授权为 MIT。重新分发前请结合所用 STM32Cube 软件包核对对应许可。
