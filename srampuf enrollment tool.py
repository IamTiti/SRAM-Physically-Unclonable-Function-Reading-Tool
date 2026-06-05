"""SRAM PUF Enrollment Tool - STM32 NUCLEO-L412KB"""
from tkinter import *
from tkinter import ttk
import tkinter as tk
import serial.tools.list_ports
import os
import time
import serial
import threading
import queue
import sys


# --------------------------------------------------------
# Threading
# --------------------------------------------------------
class ThreadedTask(threading.Thread):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def run(self):
        read_sram()
        self.queue.put("Task Finished")


def rsclick():
    progress_queue.queue.clear()
    read_button.config(state=tk.DISABLED)
    ThreadedTask(progress_queue).start()
    read_button.after(100, process_queue)


def process_queue():
    try:
        progress_queue.get_nowait()
        read_button.config(state=tk.NORMAL)
    except queue.Empty:
        read_button.after(100, process_queue)


# --------------------------------------------------------
# Main SRAM Reading Function
# --------------------------------------------------------
def read_sram():
    board     = micro_controller_list.get(ACTIVE)
    ComPort   = listbox.get(ACTIVE)
    file_name = file_input.get()

    try:
        NUM_CYCLES = int(Cycle_input.get())
    except ValueError:
        print("Please enter a valid number for cycles")
        return

    if file_name == "":
        print("Please enter a file name")
        return
    if ComPort == "":
        print("Please select a COM port")
        return
    if board == "":
        print("Please select a board")
        return

    # --------------------------------------------------------
    # STM32 NUCLEO PATH
    # --------------------------------------------------------
    if board == "STM32 NUCLEO":
        try:
            os.makedirs("./output", exist_ok=True)

            if not os.path.exists(f"./output/{file_name}.csv"):
                file_path = f"./output/{file_name}.csv"
            else:
                FILE_NUMBER = 1
                while os.path.exists(f"./output/{file_name}{FILE_NUMBER}.csv"):
                    FILE_NUMBER += 1
                file_path = f"./output/{file_name}{FILE_NUMBER}.csv"

            print(f"Output file : {file_path}")
            print(f"COM Port    : {ComPort}")
            print(f"Cycles      : {NUM_CYCLES}")
            print("Opening serial port...")

            # Open UNO serial port
            serialPort = serial.Serial(
                port     = ComPort,
                baudrate = 9600,
                stopbits = serial.STOPBITS_ONE,
                timeout  = 15
            )

            # Wait for UNO to reset
            time.sleep(2)
            serialPort.reset_input_buffer()
            print("Serial port open.")

            # ------------------------------------------------
            # Helper functions
            # ------------------------------------------------
            def uno_send(command):
                serialPort.write((command + "\n").encode("utf-8"))
                serialPort.flush()
                print(f"  TX: {command}")

            def wait_line(timeout_sec=15):
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    try:
                        raw  = serialPort.readline()
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if line:
                            return line
                    except Exception:
                        pass
                return ""

            # ------------------------------------------------
            # Wait for UNO_READY
            # ------------------------------------------------
            print("Waiting for UNO_READY...")
            deadline = time.time() + 10
            while time.time() < deadline:
                line = wait_line(2)
                if line:
                    print(f"  RX: {line}")
                if line == "UNO_READY":
                    print("UNO is ready!")
                    break

            # Ping test
            uno_send("PING")
            line = wait_line(3)
            if line:
                print(f"  RX: {line}")
            if line == "PONG":
                print("UNO ping OK!")
            else:
                print("Warning: no PONG, continuing anyway")

            # ------------------------------------------------
            # Open CSV file - old project style
            # Each row:
            # "100 AA,BB,CC,...,
            # and ends with "
            # blank line between cycles
            # ------------------------------------------------
            F = open(file_path, "w", encoding="utf-8")

            cycle_count   = 0
            BYTES_PER_ROW = 32

            # ------------------------------------------------
            # Main capture loop
            # ------------------------------------------------
            while cycle_count < NUM_CYCLES:
                print(f"\n--- Boot cycle {cycle_count + 1} of {NUM_CYCLES} ---")

                # Step 1: Power OFF NUCLEO
                uno_send("OFF")
                deadline = time.time() + 10
                while time.time() < deadline:
                    line = wait_line(2)
                    if line:
                        print(f"  RX: {line}")
                    if line == "POWER_OFF":
                        print("  NUCLEO powered off")
                        break

                print("  Waiting for power off...")
                time.sleep(3)

                # Flush before power on
                serialPort.reset_input_buffer()

                # Step 2: Power ON NUCLEO
                uno_send("ON")
                print("  NUCLEO powering on - listening immediately...")

                # Step 3: Wait for PUF_START
                found_start = False
                deadline    = time.time() + 30

                while time.time() < deadline:
                    line = wait_line(1)
                    if line == "":
                        continue

                    print(f"  RX: {line}")

                    if line in ["POWER_ON", "POWER_OFF", "UNO_READY", "PONG"]:
                        continue

                    if line == "BAD_MAGIC":
                        print("  BAD_MAGIC - mailbox invalid this cycle")
                        break

                    if line.startswith("MAGIC_VAL:"):
                        print(f"  Debug: {line}")
                        continue

                    if line == "PUF_START":
                        found_start = True
                        print("  PUF_START found!")
                        break

                if not found_start:
                    print(f"  No PUF_START for cycle {cycle_count + 1} - retrying")
                    serialPort.reset_input_buffer()
                    time.sleep(1)
                    continue

                # Step 4: Collect data until PUF_END
                byte_values = []
                found_end   = False
                deadline    = time.time() + 60

                while time.time() < deadline:
                    line = wait_line(1)
                    if line == "":
                        continue

                    if line in ["POWER_ON", "POWER_OFF", "UNO_READY", "PONG"]:
                        continue

                    if line == "PUF_END":
                        found_end = True
                        print(f"  PUF_END found. Bytes: {len(byte_values)}")
                        break

                    # Parse hex tokens
                    for token in line.split():
                        try:
                            byte_values.append(int(token, 16))
                        except ValueError:
                            pass

                # Step 5: Validate and write to CSV in old style
                if found_end and len(byte_values) == 8192:
                    address = 0x8000

                    for row_start in range(0, len(byte_values), BYTES_PER_ROW):
                        row_bytes = byte_values[row_start:row_start + BYTES_PER_ROW]

                        # Start line with quote + address + space
                        F.write(f"\"{address:X} ")

                        # Write bytes as AA,BB,CC,... with trailing comma
                        for b in row_bytes:
                            F.write(f"{b:02X},")

                        # End line with quote + newline
                        F.write("\"\n")

                        address += 0x20

                    # Blank line between cycles
                    F.write("\n")
                    F.flush()

                    cycle_count += 1
                    print(f"  Cycle {cycle_count} saved to CSV")

                else:
                    print(f"  Incomplete: {len(byte_values)} of 8192 bytes. Skipping.")
                    serialPort.reset_input_buffer()
                    time.sleep(1)

            # ------------------------------------------------
            # Done
            # ------------------------------------------------
            F.close()
            serialPort.close()
            print("\n========================================")
            print("CAPTURE COMPLETE")
            print(f"Cycles saved : {cycle_count} of {NUM_CYCLES}")
            print(f"Output file  : {file_path}")
            print("========================================")

        except Exception as e:
            print(f"Error: {e}")
            return

    # --------------------------------------------------------
    # ARDUINO MICRO PATH
    # --------------------------------------------------------
    elif board == "Arduino Micro":
        try:
            os.system(
                rf'.\avr\bin\avrdude.exe -v -V -patmega328p '
                rf'-carduino "-P{ComPort}" -b115200 '
                rf'-C "./avrdude.conf" '
                rf'"-Uflash:w:./hexfiles/ArduinoISP.ino.hex:i"'
            )
            os.system(
                rf'.\avr\bin\avrdude.exe -v -V -patmega32u4 '
                rf'-carduino -P{ComPort} -b19200 '
                rf'-C "./avrdude.conf" '
                rf'"-Uflash:w:./hexfiles/DisableWDT.hex:i"'
            )
            time.sleep(5)
            os.system(
                rf'.\avr\bin\avrdude.exe -v -V -patmega32u4 '
                rf'-carduino -P{ComPort} -b19200 '
                rf'-C "./avrdude.conf" '
                rf'"-Uflash:w:./hexfiles/ReadingMicro.hex:i"'
            )
            os.system(
                rf'.\avr\bin\avrdude.exe -v -V -patmega328p '
                rf'-carduino "-P{ComPort}" -b115200 '
                rf'-C "./avrdude.conf" '
                rf'"-Uflash:w:./hexfiles/INTERMEDIATEMICRONEW.ino.hex:i"'
            )
        except Exception as e:
            print(f"Error: {e}")
            return

    elif board == "Arduino Nano/UNO":
        print("Arduino Nano/UNO not implemented")
        return

    else:
        print("Invalid board selection")
        return


# --------------------------------------------------------
# Bootloader Burn
# --------------------------------------------------------
def burn_bootloader():
    board   = micro_controller_list.get(ACTIVE)
    ComPort = listbox.get(ACTIVE)
    if board == "Arduino Micro":
        os.system(
            rf'.\avr\bin\avrdude.exe -v -V -patmega328p '
            rf'-carduino "-P{ComPort}" -b115200 '
            rf'-C "./avrdude.conf" '
            rf'"-Uflash:w:./hexfiles/ArduinoISP.ino.hex:i"'
        )
        os.system(
            rf'.\avr\bin\avrdude.exe -CC:".\avrdude.conf" '
            rf'-v -patmega32u4 -carduino -P{ComPort} -b19200 '
            rf'-e -Ulock:w:0x3F:m -Uefuse:w:0xcb:m '
            rf'-Uhfuse:w:0xd8:m -Ulfuse:w:0xff:m'
        )
        os.system(
            rf'.\avr\bin\avrdude.exe -CC:".\avrdude.conf" '
            rf'-v -patmega32u4 -carduino -P{ComPort} -b19200 '
            rf'"-Uflash:w:./hexfiles/Caterina-Micro.hex:i" -Ulock:w:0x2F:m'
        )
    else:
        print("Burn bootloader not available for this board")


# --------------------------------------------------------
# GUI
# --------------------------------------------------------
root = Tk(screenName="Reading SRAM")
frm  = ttk.Frame(root, padding=10)
frm.grid()
root.title("SRAM PUF Enrollment Tool")

ttk.Label(
    frm,
    text="SRAM PUF Enrollment Tool",
    font=("Helvetica", 20)
).grid(column=0, row=0, columnspan=3)


def onselectlb(evt):
    Com_label.config(text=f"Selected: {listbox.get(ACTIVE)}")


def onselectmlb(evt):
    Micro_label.config(text=f"Selected: {micro_controller_list.get(ACTIVE)}")


def refresh():
    listbox.delete(0, "end")
    for p in serial.tools.list_ports.comports():
        listbox.insert(END, p.device)


com_ports       = list(serial.tools.list_ports.comports())
com_port_string = [c.device for c in com_ports]
com_var_list    = Variable(value=com_port_string)

listbox = Listbox(frm, height=5, listvariable=com_var_list)
listbox.grid(column=0, row=2)
listbox.bind("<<ListboxSelect>>", onselectlb)

possible_microcontrollers = [
    "Arduino Micro",
    "Arduino Nano/UNO",
    "STM32 NUCLEO"
]
micro_controller_list = Listbox(
    frm,
    listvariable=Variable(value=possible_microcontrollers),
    height=5
)
micro_controller_list.grid(column=1, row=2)
micro_controller_list.bind("<<ListboxSelect>>", onselectmlb)

Com_label = Label(frm, text="Selected: ")
Com_label.grid(column=0, row=1)

Micro_label = Label(frm, text="Selected: ")
Micro_label.grid(column=1, row=1)

console_frame = ttk.Frame(frm)
console_frame.grid(column=0, row=5, columnspan=3, pady=5)

console_output = Text(
    console_frame,
    height=12,
    width=65,
    state=tk.DISABLED,
    bg="black",
    fg="lime"
)
console_output.pack(side=LEFT, fill=BOTH)

scrollbar = Scrollbar(console_frame, command=console_output.yview)
scrollbar.pack(side=RIGHT, fill=Y)
console_output.config(yscrollcommand=scrollbar.set)


class ConsoleRedirect:
    def __init__(self, widget):
        self.widget = widget

    def write(self, text):
        self.widget.config(state=tk.NORMAL)
        self.widget.insert(tk.END, text)
        self.widget.see(tk.END)
        self.widget.config(state=tk.DISABLED)

    def flush(self):
        pass


sys.stdout = ConsoleRedirect(console_output)

ttk.Button(frm, text="Refresh Ports", command=refresh).grid(column=0, row=8, pady=5)

read_button = ttk.Button(frm, text="Read the SRAM", command=rsclick)
read_button.grid(column=1, row=8, pady=5)

ttk.Button(frm, text="Quit", command=root.destroy).grid(column=2, row=8, pady=5)

burn_button = ttk.Button(frm, text="Burn Bootloader", command=burn_bootloader)
burn_button.grid(column=1, row=9, pady=5)

ttk.Label(frm, text="File Name:").grid(column=0, row=10, sticky="w")
file_input = Entry(frm)
file_input.grid(column=1, row=10, sticky="w")

ttk.Label(frm, text="Number of Cycles:").grid(column=0, row=11, sticky="w")
Cycle_input = Entry(frm)
Cycle_input.grid(column=1, row=11, sticky="w")

progress_queue = queue.Queue()
root.mainloop()