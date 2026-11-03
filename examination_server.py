#!/usr/bin/env python3
"""Online Examination Network - TCP server.

Examples:
    python3 examination_server.py                          # manual START
    python3 examination_server.py --auto-start 5           # start when 5 students joined
    python3 examination_server.py --auto-start 5 --duration 120 \
        --controller-url http://127.0.0.1:8080/exam/event  # notify SDN controller
"""
import argparse
import json
import os
import socket
import threading
import time
import urllib.request
from datetime import datetime

# ---------------- CONFIGURATION (overridable via CLI) ----------------
HOST = "0.0.0.0"
PORT = 5000
EXAM_DURATION = 300
AUTO_START = 0            # 0 = manual START, N = start when N students joined
CONTROLLER_URL = None     # e.g. http://127.0.0.1:8080/exam/event

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(BASE_DIR, "exam_results.json")
QUESTIONS_FILE = os.path.join(BASE_DIR, "questions.json")
QUESTIONS = []

# ---------------- SHARED STATE ----------------
state_lock = threading.Lock()
results_lock = threading.Lock()
sessions_lock = threading.Lock()

start_event = threading.Event()
exam_state = "waiting"  # waiting, running, ended
exam_deadline = None
exam_start_wall = None
server_running = True
joined_count = 0

worker_threads = []


# ---------------- QUESTIONS ----------------
def load_questions(path):
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list) or not data:
        raise ValueError("questions file must contain a non-empty list")
    for index, item in enumerate(data, start=1):
        if not {"question", "options", "answer"} <= set(item):
            raise ValueError(f"question {index} is missing a field")
        if str(item["answer"]).upper() not in ("A", "B", "C", "D"):
            raise ValueError(f"question {index} has an invalid answer")
        item["answer"] = str(item["answer"]).upper()
    return data


# ---------------- SDN CONTROLLER NOTIFICATION ----------------
def notify_controller(event, extra=None, block=False):
    """POST a JSON event to the SDN controller (best effort)."""
    if not CONTROLLER_URL:
        return

    payload = {
        "event": event,                # "exam_start" or "exam_end"
        "port": PORT,
        "duration": EXAM_DURATION,
        "students": joined_count,
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        payload.update(extra)

    def _send():
        try:
            request = urllib.request.Request(
                CONTROLLER_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(request, timeout=2).close()
            print(f"[CONTROLLER] Notified: {event}")
        except Exception as error:  # controller may be down; exam continues
            print(f"[CONTROLLER] Could not notify ({event}): {error}")

    if block:
        _send()
    else:
        threading.Thread(target=_send, daemon=True).start()


# ---------------- NETWORK MESSAGES ----------------
def send_message(session, message):
    data = (json.dumps(message) + "\n").encode("utf-8")
    with session["send_lock"]:
        session["conn"].sendall(data)


def receive_message(session):
    """Receive one newline-delimited JSON message."""
    conn = session["conn"]
    buffer = session["buffer"]

    while b"\n" not in buffer:
        with state_lock:
            state = exam_state
            deadline = exam_deadline

        if state == "running":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Common exam deadline reached.")
            conn.settimeout(min(0.5, remaining))
        else:
            conn.settimeout(0.5)

        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            continue

        if not chunk:
            raise ConnectionError("Student disconnected.")

        buffer.extend(chunk)

    line, _, extra = buffer.partition(b"\n")
    buffer[:] = extra

    with state_lock:
        state = exam_state
        deadline = exam_deadline

    if state == "running" and time.monotonic() >= deadline:
        raise TimeoutError("Common exam deadline reached.")

    message = json.loads(line.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("Invalid message format.")

    return message


# ---------------- PERSISTENT RESULTS ----------------
def save_result(result):
    with results_lock:
        records = []

        if os.path.exists(RESULTS_FILE):
            try:
                with open(RESULTS_FILE, "r", encoding="utf-8") as file:
                    records = json.load(file)
                if not isinstance(records, list):
                    records = []
            except (OSError, json.JSONDecodeError):
                records = []

        records.append(result)

        temp_file = RESULTS_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(records, file, indent=4)

        os.replace(temp_file, RESULTS_FILE)

    print(f"[SAVED] Result for {result['name']}")


def finish_student(session, status):
    """Save each student's result at most once."""
    with session["finish_lock"]:
        if session["saved"] or not session["logged_in"]:
            return

        session["saved"] = True

        with state_lock:
            start_wall = exam_start_wall

        result = {
            "name": session["name"],
            "address": session["address"][0],
            "score": session["score"],
            "total": len(QUESTIONS),
            "attempted": session["attempted"],
            "status": status,
            "joined_at": session["joined_at"],
            "exam_started_at": (
                datetime.fromtimestamp(start_wall).isoformat(timespec="seconds")
                if start_wall is not None else None
            ),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            save_result(result)
        except OSError as error:
            print(f"[ERROR] Could not save result: {error}")

        try:
            send_message(session, {"type": "result", **result})
        except OSError:
            pass

        print(
            f"[RESULT] {session['name']}: "
            f"{session['score']}/{len(QUESTIONS)}, "
            f"attempted={session['attempted']}, status={status}"
        )


# ---------------- STUDENT SESSION ----------------
def handle_student(conn, address):
    global joined_count

    session = {
        "conn": conn,
        "address": address,
        "send_lock": threading.Lock(),
        "finish_lock": threading.Lock(),
        "buffer": bytearray(),
        "name": "Unknown",
        "logged_in": False,
        "saved": False,
        "score": 0,
        "attempted": 0,
        "joined_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        with state_lock:
            state = exam_state
            deadline = exam_deadline

        if state == "ended" or (
            state == "running" and time.monotonic() >= deadline
        ):
            send_message(session, {
                "type": "rejected",
                "message": "The exam has ended. Late entry is not allowed."
            })
            return

        send_message(session, {
            "type": "welcome",
            "message": "Welcome to the Online Examination Network!",
            "duration": EXAM_DURATION
        })

        login = receive_message(session)
        if login.get("type") != "login":
            return

        session["name"] = (
            str(login.get("name", "Student")).strip()[:50] or "Student"
        )

        should_start = False
        with state_lock:
            if exam_state == "ended" or (
                exam_state == "running"
                and time.monotonic() >= exam_deadline
            ):
                send_message(session, {
                    "type": "rejected",
                    "message": "The exam deadline has passed."
                })
                return

            session["logged_in"] = True
            joined_count += 1
            state = exam_state
            if AUTO_START > 0 and exam_state == "waiting" \
                    and joined_count >= AUTO_START:
                should_start = True

        print(f"[JOINED] {session['name']} from {address} "
              f"(total joined: {joined_count})")

        if should_start:
            start_exam()
            state = "running"

        if state == "waiting":
            send_message(session, {
                "type": "waiting",
                "message": "You are in the lobby. Waiting for the exam to start."
            })
            start_event.wait()

        with state_lock:
            state = exam_state
            deadline = exam_deadline
            start_wall = exam_start_wall

        if state == "ended" or time.monotonic() >= deadline:
            finish_student(session, "timed_out")
            return

        late_join = time.time() > start_wall + 1

        send_message(session, {
            "type": "exam_started",
            "message": (
                "You joined an exam already in progress."
                if late_join else "The exam has started!"
            ),
            "duration": EXAM_DURATION,
            "remaining": max(0, deadline - time.monotonic()),
            "late_join": late_join,
            "deadline": datetime.fromtimestamp(
                start_wall + EXAM_DURATION
            ).isoformat(timespec="seconds")
        })

        for number, question in enumerate(QUESTIONS, start=1):
            if time.monotonic() >= deadline:
                finish_student(session, "timed_out")
                return

            send_message(session, {
                "type": "question",
                "number": number,
                "total": len(QUESTIONS),
                "question": question["question"],
                "options": question["options"],
                "remaining": max(0, deadline - time.monotonic())
            })

            response = receive_message(session)

            if response.get("type") != "answer":
                finish_student(session, "invalid_message")
                return

            choice = str(response.get("choice", "")).strip().upper()
            if choice not in ("A", "B", "C", "D"):
                finish_student(session, "invalid_answer")
                return

            session["attempted"] += 1
            if choice == question["answer"]:
                session["score"] += 1

        finish_student(session, "completed")

    except TimeoutError:
        finish_student(session, "timed_out")
    except (ConnectionError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[CONNECTION] {session['name']} ({address}): {error}")
        finish_student(session, "disconnected")
    finally:
        try:
            conn.close()
        except OSError:
            pass


# ---------------- CONNECTION ACCEPTOR ----------------
def accept_students(server):
    while server_running:
        try:
            conn, address = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        thread = threading.Thread(
            target=handle_student, args=(conn, address), daemon=False
        )

        with sessions_lock:
            worker_threads.append(thread)

        thread.start()


# ---------------- EXAM START ----------------
def start_exam():
    global exam_state, exam_deadline, exam_start_wall

    with state_lock:
        if exam_state != "waiting":
            print("[INFO] Exam has already started or ended.")
            return

        exam_start_wall = time.time()
        exam_deadline = time.monotonic() + EXAM_DURATION
        exam_state = "running"
        start_event.set()

    print("\n" + "=" * 55)
    print("[EXAM STARTED] All lobby students may begin.")
    print(f"Duration: {EXAM_DURATION} seconds")
    print("Late joining: enabled until the common deadline")
    print("Deadline:", datetime.fromtimestamp(
        exam_start_wall + EXAM_DURATION).strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 55)

    notify_controller("exam_start")


def parse_args():
    parser = argparse.ArgumentParser(description="Online Examination Server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--duration", type=int, default=EXAM_DURATION,
                        help="exam length in seconds")
    parser.add_argument("--questions", default=QUESTIONS_FILE)
    parser.add_argument("--results", default=RESULTS_FILE)
    parser.add_argument("--auto-start", type=int, default=0, metavar="N",
                        help="start automatically when N students have joined")
    parser.add_argument("--controller-url", default=None,
                        help="HTTP endpoint on the SDN controller for events")
    return parser.parse_args()


def main():
    global server_running, exam_state
    global HOST, PORT, EXAM_DURATION, AUTO_START, CONTROLLER_URL
    global RESULTS_FILE, QUESTIONS

    args = parse_args()
    HOST, PORT = args.host, args.port
    EXAM_DURATION = args.duration
    AUTO_START = args.auto_start
    CONTROLLER_URL = args.controller_url
    RESULTS_FILE = os.path.abspath(args.results)
    QUESTIONS = load_questions(args.questions)

    print("=" * 55)
    print("ONLINE EXAMINATION NETWORK - SERVER")
    print("=" * 55)
    print(f"Listening on TCP {HOST}:{PORT}")
    print(f"Questions: {len(QUESTIONS)} | Duration: {EXAM_DURATION}s")
    print(f"Results file: {RESULTS_FILE}")
    print(f"Controller URL: {CONTROLLER_URL or 'not set'}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(100)
    server.settimeout(0.5)

    threading.Thread(target=accept_students, args=(server,),
                     daemon=True).start()

    try:
        if AUTO_START > 0:
            print(f"Auto-start: exam begins when {AUTO_START} students join.")
            while not start_event.wait(0.5):
                pass
        else:
            print("Type START and press Enter to begin the exam.")
            while True:
                command = input("Admin command (START / QUIT): ").strip().upper()
                if command == "START":
                    start_exam()
                    break
                elif command == "QUIT":
                    with state_lock:
                        exam_state = "ended"
                    start_event.set()      # release students in the lobby
                    server_running = False
                    server.close()
                    print("Server stopped before the exam started.")
                    return
                else:
                    print("Unknown command. Type START or QUIT.")

        with state_lock:
            deadline = exam_deadline

        while time.monotonic() < deadline:
            time.sleep(0.2)

        with state_lock:
            exam_state = "ended"

        print("\n[DEADLINE] The common exam deadline has passed.")
        server_running = False
        server.close()

        notify_controller("exam_end", block=True)

        with sessions_lock:
            workers = list(worker_threads)
        for thread in workers:
            thread.join(timeout=2)

        print(f"[DONE] Results are stored in: {RESULTS_FILE}")

    except (KeyboardInterrupt, EOFError):
        print("\n[STOP] Server shutdown requested.")
        server_running = False
        with state_lock:
            exam_state = "ended"
        start_event.set()
        server.close()


if __name__ == "__main__":
    main()
