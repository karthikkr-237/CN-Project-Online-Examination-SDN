#!/usr/bin/env python3
"""Summarise exam response time and fairness for the three scenarios.

Reads   results/<scenario>/h*.csv   (written by examination_client.py --csv)
        results/<scenario>/udp.txt  (iperf3 --logfile output, if present)
Writes  results/summary_results.csv
        results/response_time_comparison.png  (if matplotlib is installed)

Run from the repository root:   python3 analyze_results.py
"""
import csv
import glob
import os
import re
import statistics as st

SCENARIOS = [('normal',  '1. Normal'),
             ('static',  '2. Congested\nstatic'),
             ('dynamic', '3. Congested\ndynamic SDN')]

# In the recorded dynamic run, the h3 client was accidentally started twice,
# so its CSV mixes two sessions. It is excluded from the analysis.
EXCLUDE = {('dynamic', 'h3')}

OUT_DIR = 'results'


def pct(values, p):
    """Percentile with linear interpolation."""
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def jain(values):
    """Jain's fairness index: (sum x)^2 / (n * sum x^2). 1.0 = perfectly fair."""
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values))


summary = []
for key, label in SCENARIOS:
    all_ms, per_student, completed = [], {}, 0
    for path in sorted(glob.glob(f'{OUT_DIR}/{key}/h*.csv')):
        name = os.path.basename(path)[:-4]
        if (key, name) in EXCLUDE:
            continue
        with open(path) as f:
            rows = list(csv.DictReader(f))
        ms = []
        for r in rows:
            try:
                ms.append(float(r['response_time_s']) * 1000)
            except (ValueError, KeyError, TypeError):
                pass
        if rows and rows[-1].get('status') == 'completed':
            completed += 1
        if ms:
            per_student[name] = ms
            all_ms += ms

    if not all_ms:
        print(f'{key}: no data found')
        continue

    loss = 'no UDP'
    udp = f'{OUT_DIR}/{key}/udp.txt'
    if os.path.exists(udp):
        m = re.findall(r'\((\d+(?:\.\d+)?)%\)\s+receiver', open(udp).read())
        loss = (m[-1] + '%') if m else 'not found'

    # Fairness: per-student service rate = 1 / mean response time
    # (answers served per second of waiting on the network + server).
    means = {n: st.mean(v) for n, v in per_student.items()}
    rates = [1000.0 / m for m in means.values()]

    summary.append(dict(
        scenario=key, label=label, completed=completed, samples=len(all_ms),
        mean=st.mean(all_ms), median=st.median(all_ms),
        p95=pct(all_ms, 95), max=max(all_ms), udp_loss=loss,
        jain=jain(rates),
        per_student=' '.join(f'{n}={m:.1f}' for n, m in means.items())))

print('\nExam response time (ms): answer sent -> next question/result received')
print(f"{'Scenario':<10}{'Samples':>8}{'Done':>6}{'Mean':>9}{'Median':>9}"
      f"{'P95':>9}{'Max':>9}{'Jain':>7}  UDP loss   Per-student mean (ms)")
for s in summary:
    print(f"{s['scenario']:<10}{s['samples']:>8}{s['completed']:>6}{s['mean']:>9.1f}"
          f"{s['median']:>9.1f}{s['p95']:>9.1f}{s['max']:>9.1f}{s['jain']:>7.3f}"
          f"  {s['udp_loss']:<10} {s['per_student']}")

os.makedirs(OUT_DIR, exist_ok=True)
summary_path = os.path.join(OUT_DIR, 'summary_results.csv')
with open(summary_path, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['scenario', 'samples', 'clients_completed', 'mean_ms', 'median_ms',
                'p95_ms', 'max_ms', 'jain_fairness', 'udp_receiver_loss',
                'per_student_mean_ms'])
    for s in summary:
        w.writerow([s['scenario'], s['samples'], s['completed'], f"{s['mean']:.1f}",
                    f"{s['median']:.1f}", f"{s['p95']:.1f}", f"{s['max']:.1f}",
                    f"{s['jain']:.3f}", s['udp_loss'], s['per_student']])
print(f'\nSaved {summary_path}')

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    labels = [s['label'] for s in summary]
    x = range(len(summary))
    width = 0.27
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (field, name) in enumerate([('median', 'Median'), ('mean', 'Mean'),
                                       ('p95', '95th percentile')]):
        vals = [s[field] for s in summary]
        bars = ax.bar([xi + (i - 1) * width for xi in x], vals, width, label=name)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f'{v:.0f}',
                    ha='center', va='bottom', fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel('Response time (ms)')
    ax.set_title('Exam response time: normal vs congested (static vs dynamic SDN)')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    graph_path = os.path.join(OUT_DIR, 'response_time_comparison.png')
    fig.savefig(graph_path, dpi=150)
    print(f'Saved {graph_path}')
except ImportError:
    print('matplotlib not installed - table and CSV saved, graph skipped')
