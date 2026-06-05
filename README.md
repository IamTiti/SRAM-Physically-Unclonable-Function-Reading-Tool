# SRAM-Physically-Unclonable-Function-Reading-Tool
This project uses the startup state of SRAM2 on an STM32 NUCLEO-L412KB as a Physical Unclonable Function (PUF). An Arduino Uno power-cycles the NUCLEO and collects SRAM data over UART, while a Python GUI automates multiple capture cycles and stores the results for PUF analysis.
