# Online Examination Network - Socket Part

Files: `examination_server.py`, `examination_client.py`, `questions.json`

## Protocol (TCP, port 5000, newline-delimited JSON)
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

## Run in Mininet (server on h1 = 10.0.0.1)
    mininet> h1 python3 examination_server.py --auto-start 4 --duration 120 --controller-url http://127.0.0.1:8080/exam/event &
    mininet> h2 python3 examination_client.py 10.0.0.1 --auto --name s1 --think-time 2 --quiet &
    ... (h3, h4, h5 likewise)

## Controller notification (for the SDN teammate)
The server sends `POST <controller-url>` with JSON:
`{"event": "exam_start" | "exam_end", "port": 5000, "duration": 120, "students": 4, "time": "..."}`
Use it to raise priority for TCP/5000 on start and restore on end.
If the controller is unreachable the exam still runs.

## Metrics
Each client writes `logs/<name>.csv`:
`name, question, think_time_s, response_time_s, total_time_s, score, status`.
`response_time_s` = answer sent -> next question received (network + server delay).
Merge: `head -1 logs/s1.csv > all.csv; tail -q -n +2 logs/*.csv >> all.csv`
Fairness: compute Jain's index over per-student mean `response_time_s` or `total_time_s`.

## Other options
`--auto-start N` start when N joined | `--duration S` | `--questions file.json` | `--results file.json` | `--port P`
