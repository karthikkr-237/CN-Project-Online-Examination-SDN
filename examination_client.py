#!/usr/bin/env python3
"""Online Examination Network - TCP client.

Interactive:   python3 examination_client.py 10.0.0.1
Automated:     python3 examination_client.py 10.0.0.1 --auto --name s3 --think-time 2

Metrics written per student to logs/<name>.csv:
  think_time_s    = question received -> answer sent (student/app delay)
  response_time_s = answer sent -> next question/result received
                    (network + server delay: the value to compare across
                     congestion / SDN experiments)
"""
import argparse
import csv
import json
import os
import queue
import random
import socket
import threading
import time

server_messages = queue.Queue()
user_answers = queue.Queue()
STOP = object()


def send_message(sock, message):
    sock.sendall((json.dumps(message) + "\n").encode("utf-8"))


def read_server(sock):
    """Read messages continuously; timestamp each on arrival."""
    buffer = bytearray()
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            while b"\n" in buffer:
                line, _, extra = buffer.partition(b"\n")
                buffer = bytearray(extra)
                message = json.loads(line.decode("utf-8"))
                message["_recv"] = time.monotonic()
                server_messages.put(message)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        server_messages.put({"type": "connection_error", "message": str(error)})
    finally:
        server_messages.put(STOP)


def ask_answer(number, total, question, options):
    print(f"\nQuestion {number}/{total}: {question}")
    for option in options:
        print(option)
    while True:
        try:
            choice = input("Enter A, B, C or D: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            return
        if choice in ("A", "B", "C", "D"):
            user_answers.put(choice)
            return
        print("Invalid choice. Enter A, B, C or D.")


def write_csv(path, name, rows, total_time, score, status):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if new_file:
            writer.writerow(["name", "question", "think_time_s",
                             "response_time_s", "total_time_s",
                             "score", "status"])
        for row in rows:
            response = row["response"]
            writer.writerow([
                name, row["question"], f"{row['think']:.4f}",
                "" if response is None else f"{response:.4f}",
                "" if total_time is None else f"{total_time:.4f}",
                score, status,
            ])


def connect(host, port, retries):
    for attempt in range(retries + 1):
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.settimeout(None)
            return sock
        except OSError:
            if attempt == retries:
                raise
            time.sleep(1)


def run(args):
    log = (lambda *a: None) if args.quiet else print
    name = args.name or (f"student-{os.getpid()}" if args.auto else None)
    rows, pending = [], None
    deadline = exam_start = None
    score = "NA"
    status = "no_result"
    total_time = None
    active = None  # interactive question in progress

    try:
        client = connect(args.server, args.port, args.retries)
    except OSError as error:
        print(f"Cannot connect to {args.server}:{args.port} ({error}).")
        return

    with client:
        threading.Thread(target=read_server, args=(client,), daemon=True).start()

        first = server_messages.get()
        if first is STOP:
            print("Server disconnected.")
            return
        if first.get("type") == "rejected":
            print(first.get("message", "Entry rejected."))
            return
        if first.get("type") != "welcome":
            print("Unexpected message from server.")
            return

        log("\n" + "=" * 45)
        log(first["message"])
        log("=" * 45)

        if name is None:
            name = input("Enter your name: ").strip() or "Student"
        send_message(client, {"type": "login", "name": name})

        def submit(number, choice, think):
            nonlocal pending
            if deadline is not None and time.monotonic() >= deadline:
                print("\nTime expired. Answer was not submitted.")
                return
            try:
                pending = {"question": number, "think": think,
                           "t_sent": time.monotonic()}
                send_message(client, {"type": "answer",
                                      "question": number, "choice": choice})
            except OSError:
                pending = None
                print("Could not submit answer: connection lost.")

        while True:
            try:
                message = server_messages.get(timeout=0.2)
            except queue.Empty:
                message = None

            if message is STOP:
                log("\nServer connection closed.")
                break

            if message is not None:
                kind = message.get("type")

                # latency of the previous answer = until next question/result
                if pending and kind in ("question", "result"):
                    pending["response"] = message["_recv"] - pending["t_sent"]
                    rows.append(pending)
                    pending = None

                if kind == "waiting":
                    log("\n" + message["message"])

                elif kind == "exam_started":
                    deadline = time.monotonic() + message["remaining"]
                    exam_start = message.get("_recv", time.monotonic())
                    log("\n" + message["message"])
                    log("Common deadline:", message["deadline"])

                elif kind == "question":
                    number = message["number"]
                    if args.auto:
                        base = args.think_time
                        think = random.uniform(
                            max(0.0, base * (1 - args.jitter)),
                            base * (1 + args.jitter))
                        time.sleep(think)
                        submit(number, random.choice("ABCD"), think)
                        log(f"[{name}] answered Q{number}/{message['total']}")
                    else:
                        active = {"number": number, "t_recv": message["_recv"]}
                        threading.Thread(
                            target=ask_answer,
                            args=(number, message["total"],
                                  message["question"], message["options"]),
                            daemon=True).start()

                elif kind == "result":
                    score = f"{message['score']}/{message['total']}"
                    status = message["status"]
                    total_time = (message["_recv"] - exam_start
                                  if exam_start else None)
                    print(f"[{name}] RESULT: {score}, attempted="
                          f"{message['attempted']}, status={status}")
                    break

                elif kind == "rejected":
                    print("\n" + message.get("message", "Entry rejected."))
                    break

                elif kind == "connection_error":
                    print("\nConnection error:", message["message"])
                    status = "connection_error"
                    break

            if active:
                try:
                    choice = user_answers.get_nowait()
                except queue.Empty:
                    continue
                think = time.monotonic() - active["t_recv"]
                number, active = active["number"], None
                submit(number, choice, think)

    if pending:  # last answer never got a reply
        pending["response"] = None
        rows.append(pending)
    write_csv(args.csv or os.path.join("logs", f"{name}.csv"),
              name, rows, total_time, score, status)


def main():
    parser = argparse.ArgumentParser(description="Online Examination Client")
    parser.add_argument("server", nargs="?", default="127.0.0.1",
                        help="server IP (e.g. 10.0.0.1 in Mininet)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--name", default=None)
    parser.add_argument("--auto", action="store_true",
                        help="answer randomly without keyboard input")
    parser.add_argument("--think-time", type=float, default=2.0,
                        help="mean seconds before answering (auto mode)")
    parser.add_argument("--jitter", type=float, default=0.5,
                        help="think-time variation, 0.5 = +/-50%%")
    parser.add_argument("--csv", default=None,
                        help="metrics file (default logs/<name>.csv)")
    parser.add_argument("--retries", type=int, default=5,
                        help="connection retries, 1 s apart")
    parser.add_argument("--quiet", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExited.")
