#!/usr/bin/env python3

"""
Copyright 2021 Leon Läufer

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies
or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


import sys
import time
import asyncio
import signal
import os


def dump_to_csv(filehandle, state, pids):
    header = ""
    for pid in sorted(pids):
        header += "epoch_time, total_cpu, "+str(pid)+"_cpu, "+str(pid)+"_mem, "
    header = header[:-2]+"\n"
    filehandle.write(header)
    sorted_keys = sorted(state.keys(), key=lambda x: int(x))
    for key in sorted_keys:
        timeframe = state[key]
        line = ""
        filehandle.write((str(timeframe["TIME"])+", "))
        filehandle.write(str(timeframe["TOTAL"]["CPU"])+", ")
        del timeframe["TOTAL"]
        for pid in pids:
            if str(pid) in timeframe.keys():
                line += str(timeframe[str(pid)]["CPU"])+", "+str(timeframe[str(pid)]["MEM"])+", "
            else:
                line += ", , "
        line = line[:-2]+"\n"
        filehandle.write(line)


def dump_to_json(filehandle, state, interval):
    state["INTERVAL"] = interval
    filehandle.write(str(state).replace("'", '"').replace("True", "true").replace("False", "false"))


async def get_resource_stats(interval, filetype, output_file, pids):
    cpu_usage = dict()
    global_cpu_usage = 0.0

    def clear_ascii_escape(text):
        return text.replace('\x1b(B', '').replace('\x1b[m', '').replace('\x1b[39;49m', '').replace('\x1b[1m', '').\
            replace('\x1b[K', '').replace('\x1b[J', '').replace('\x1b[H', '').replace('\x1b[7m', '')

    def get_memory_usage(pid):
        return float((os.popen('cat /proc/' + str(
            pid) + '/smaps | grep -i pss |  awk \'{sum+=$2} END {print sum/1024""}\'').read()).replace(",", "."))

    def get_cpu_usage(pid):
        return cpu_usage[int(pid)]

    def set_cpu_usage(pid, usage):
        nonlocal cpu_usage
        cpu_usage[int(pid)] = usage

    def get_global_cpu_usage():
        return global_cpu_usage

    def set_global_cpu_usage(usage):
        nonlocal global_cpu_usage
        global_cpu_usage = usage

    def get_cpu_thread_count():
        return int(os.popen('grep -c processor /proc/cpuinfo').read())

    def is_running(pid):
        return str(pid) in os.popen('ps -p ' + str(pid)).read()

    for pid in pids:
        set_cpu_usage(pid, 0.0)

    cpu_threads = get_cpu_thread_count()
    pidlst = str(pids)[1:-1].replace(" ", "")
    code = 'top -d '+str(interval)+' -p '+pidlst+' -o PID'

    proc = await asyncio.create_subprocess_shell(code, stdout=asyncio.subprocess.PIPE)
    time.sleep(1)
    current_epoch = 0
    captured_data = dict()

    def signal_handler(sig, frame):
        print("Logging halted! Saving log to ", output_file, " as ", filetype, "!", sep="")
        with open(output_file, 'w') as outfile:
            if filetype == "json":
                dump_to_json(outfile, captured_data, interval)
            else:
                dump_to_csv(outfile, captured_data, pids)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    epoch_time = -1

    while True:
        data = await proc.stdout.readline()
        line = data.decode('ascii').rstrip()
        if len(line) > 5:  # Sort out invalid lines
            line_split = clear_ascii_escape(line).split()
            if line.startswith('%Cpu(s):\x1b(B\x1b[m\x1b[39;49m\x1b[1m'):  # Get CPU usage
                try:
                    set_global_cpu_usage(round((100.0-float(line_split[7].replace(",", ".")))*cpu_threads, 1))
                except:
                    print("CPU usage could not be logged, increase your interval if this issue persists")
            elif line.startswith('\x1b(B\x1b[m'):  # Get CPU usage of pids
                try:
                    set_cpu_usage(line_split[0], float(line_split[8].replace(",", ".")))
                except:
                    print("Thread CPU usage could not be logged, increase your interval if this issue persists")

            current_time = time.time()
            if epoch_time + interval < current_time:
                if epoch_time == -1:
                    epoch_time = current_time
                else:
                    epoch_time += interval
                    current_epoch += 1
                    # Update to current epoch if there was a delay in the program
                    while epoch_time + interval < current_time:
                        print("There was a delay in the program, trying to fill in the data")
                        print("Use a longer interval if this problem persists")
                        current_data = captured_data.get(str(current_epoch-1), dict()).copy()
                        current_data["TIME"] = epoch_time
                        current_data["LAG-COMPENSATION"] = True
                        captured_data[str(current_epoch)] = current_data
                        epoch_time += interval
                        current_epoch += 1
                current_data = captured_data.get(str(current_epoch), dict())
                current_data["TIME"] = epoch_time
                current_data["LAG-COMPENSATION"] = False
                print("TIME: ", epoch_time, sep="")
                # Log and print total CPU utilization
                total = dict()
                total["CPU"] = get_global_cpu_usage()
                current_data["TOTAL"] = total
                captured_data[str(current_epoch)] = current_data
                print("TOTAL CPU: ", get_global_cpu_usage(), "%", sep="")

                # Log and print data of all pids
                for pid in pids:
                    if is_running(pid):
                        current_data_pid = current_data.get(int(pid), dict())
                        try:
                            mem_size = get_memory_usage(pid)
                        except:
                            mem_size = 0.0
                        current_data_pid["CPU"] = get_cpu_usage(pid)
                        current_data_pid["MEM"] = mem_size
                        current_data[str(pid)] = current_data_pid
                        captured_data[str(current_epoch)] = current_data
                        print(pid, ": CPU: ", get_cpu_usage(pid), "% MEM: ", str(mem_size), " MiB", sep="")
                print()


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python3 %s <interval> <type> <file> <pid1> [<pid2>] [<pid3>] [<pid4>] ..." % sys.argv[0])
        print("Interval in seconds, Type: json or csv")
        sys.exit(1)
    print("Press Ctrl+C to stop logging!")
    interval = float(sys.argv[1])
    filetype = str(sys.argv[2])
    output_file = str(sys.argv[3])
    pids = list(map(lambda x: int(x), sys.argv[4:]))
    asyncio.run(get_resource_stats(interval, filetype, output_file, pids))
