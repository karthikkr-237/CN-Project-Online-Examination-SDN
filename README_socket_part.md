# Online Examination Network - Socket Part

Files: `examination_server.py`, `examination_client.py`, `questions.json`

## Protocol (TCP, port 5000, newline-delimited JSON)

Each message is a JSON object followed by a newline (`\n`). The newline marks the end of one message, while JSON provides named, structured fields. This is easier to read and extend than the original pipe-delimited format: new fields can be added without relying on field position or custom pipe parsing.

| Direction | type | Fields |
|---|---|---|
| S->C | welcome | message, duration |
| C->S | login | name |
| S->C | waiting | message |
| S->C | exam_started | remaining, deadline, late_join |
| S->C | question | number, total, question, options, remaining |
| C->S | answer | question, choice (A-D) |
| S->C | result | name, score, total, attempted, status |
| S->C | rejected | message |

## Run in Mininet (final topology)

The examination server runs on `s_server` at `10.0.0.4:5000`. Student clients run on `h1`, `h2`, and `h3`.

    mininet> s_server python3 examination_server.py --auto-start 3 --duration 120 &
    mininet> h1 python3 examination_client.py 10.0.0.4 --auto --name student1 --think-time 2 --quiet &
    mininet> h2 python3 examination_client.py 10.0.0.4 --auto --name student2 --think-time 2 --quiet &
    mininet> h3 python3 examination_client.py 10.0.0.4 --auto --name student3 --think-time 2 --quiet &

Note: avoid student names that match Mininet node names (such as `s1`, `s2`, `s3`, `h1`): the Mininet CLI rewrites node names in commands (for example, `h1` becomes `10.0.0.1`).

Use the project's configured server/client options as needed. The final demo does not use `--controller-url`: the controller has no HTTP endpoint, and QoS/priority changes are outside the scope of this setup.

## Metrics

Each client writes to `logs/<name>.csv`:
`name, question, think_time_s, response_time_s, total_time_s, score, status`.

`response_time_s` = answer sent -> next question or final result received (network + server delay; student think time is not included).

The client appends to CSV files, and the server appends each run's records to its results file (`exam_results.json` by default). For repeated runs, use a fresh output folder for each run and pass both a fresh `--csv` path to each client and a fresh `--results` path to the server, for example:

    mininet> s_server python3 examination_server.py --auto-start 3 --duration 120 --results results/run1/server_results.json &
    mininet> h1 python3 examination_client.py 10.0.0.4 --auto --name student1 --think-time 2 --csv results/run1/student1.csv &

Merge:
`head -1 logs/student1.csv > all.csv; tail -q -n +2 logs/*.csv >> all.csv`

For fairness, compute Jain's fairness index over per-student throughput values (not response time). Use a consistent measurement interval and define throughput consistently, for example completed questions per second or completed exams per second.

## Known limitation

Duplicate logins are not currently rejected. If the same student/client logs in more than once, the server may accept multiple sessions and produce multiple result records for that student/IP. The original `ALREADY_LOGGED_IN` behavior is not implemented in the tested version.
