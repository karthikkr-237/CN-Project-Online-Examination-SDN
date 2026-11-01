# Online Examination Network over SDN

**Computer Networks Project | Project 18**

A multi-client TCP-based Online Examination System integrated with Software-Defined Networking (SDN), using Mininet, Open vSwitch and the Ryu Controller.

The project explores how SDN can dynamically manage examination traffic under network congestion through real-time traffic monitoring and intelligent rerouting.

---

## Project Overview

Traditional online examination systems depend on reliable network connectivity to deliver questions, receive student responses and calculate examination results.

However, network congestion can introduce significant latency, packet loss and delayed submissions, affecting the examination experience.

This project addresses this problem by developing a TCP-based online examination application and deploying it within an SDN-controlled Mininet network.

The SDN controller monitors network traffic and dynamically reroutes examination-related TCP traffic through an alternate network path when congestion is detected on the primary path.

The system is evaluated under different network conditions to analyse the effectiveness of dynamic SDN-based traffic management.

## Key Features

* Multi-client TCP socket communication.
* Concurrent student connections using Python threading.
* Automated question delivery and answer submission.
* Examination timer and automatic result calculation.
* SDN-based network monitoring using OpenFlow 1.3.
* Congestion detection using network traffic statistics.
* Dynamic rerouting of examination traffic.
* UDP-based background traffic generation for congestion testing.
* Automated performance benchmarking.
* Latency, throughput and fairness analysis.

---

## Technology Stack

| Component                 | Technology               |
| ------------------------- | ------------------------ |
| Programming Language      | Python 3                 |
| Network Emulator          | Mininet 2.3.0+           |
| Virtual Switching         | Open vSwitch             |
| SDN Controller            | Ryu Controller           |
| Southbound Protocol       | OpenFlow 1.3             |
| Application Communication | TCP Sockets              |
| Concurrency               | Python Threading         |
| Congestion Generation     | iPerf (UDP)              |
| Performance Analysis      | Python, Matplotlib       |
| Operating Environment     | Ubuntu 20.04 / 22.04 LTS |

---

## System Architecture

The project consists of two major components:

### 1. Online Examination Application

The application provides communication between multiple student clients and a central examination server.

Responsibilities include:

* Student authentication.
* Question distribution.
* Answer submission.
* Examination time management.
* Answer evaluation.
* Result generation.

### 2. SDN-Controlled Network

The network is emulated using Mininet and managed by a Ryu SDN controller.

The controller monitors traffic on the primary network path. When congestion crosses the predefined threshold, it installs appropriate OpenFlow rules to redirect examination-related TCP traffic through an alternate path.

### Network Topology

The project uses a three-switch triangular topology.

```text
                 h1    h2    h3    h_bad
                  \     |     |     /
                   \    |     |    /
                    ┌───────────┐
                    │    S1     │
                    └─────┬─────┘
                         / \
                        /   \
               Primary /     \ Alternate
                      /       \
                ┌──────┐     ┌──────┐
                │  S2  │     │  S3  │
                └──┬───┘     └──┬───┘
                   |             |
                   └─────┬───────┘
                         |
                    Exam Server
                      10.0.0.4
```

**Primary path:** S1 → S2
**Alternate path:** S1 → S3 → S2

### Network Addressing

| Node     | IP Address | Role                     |
| -------- | ---------- | ------------------------ |
| h1       | 10.0.0.1   | Student Client 1         |
| h2       | 10.0.0.2   | Student Client 2         |
| h3       | 10.0.0.3   | Student Client 3         |
| s_server | 10.0.0.4   | Examination Server       |
| h_bad    | 10.0.0.5   | UDP Congestion Generator |

**Examination Server Port:** 5000

---

## Congestion Detection and Dynamic Rerouting

The primary network link has a bandwidth capacity of 10 Mbps.

A background UDP traffic stream of 9 Mbps is generated to simulate network congestion.

The Ryu controller periodically monitors network statistics using OpenFlow port statistics.

When the measured throughput crosses the predefined threshold of **7.5 Mbps**, the controller triggers its mitigation mechanism.

It installs higher-priority flow rules to redirect examination-related TCP traffic (destination port 5000) through the alternate path.

The background UDP traffic continues through the primary path.

This allows the examination traffic to avoid the congested link.

---

## Performance Evaluation

The system is evaluated under three experimental scenarios.

| Scenario   | Network Condition                            | Objective                      |
| ---------- | -------------------------------------------- | ------------------------------ |
| Scenario 1 | Normal network conditions                    | Establish baseline performance |
| Scenario 2 | Congested network with static routing        | Measure network degradation    |
| Scenario 3 | Congested network with dynamic SDN rerouting | Evaluate SDN-based improvement |

### Performance Metrics

The following metrics are collected:

1. **Application-Level RTT:** Measures the time taken between answer transmission and acknowledgement/next-question reception.
2. **Throughput:** Measures useful application payload delivered per unit time.
3. **Jain's Fairness Index:** Evaluates how evenly network performance is distributed among student clients.

Results are collected through automated benchmarking and visualized using Python.

All performance results are based on actual experimental measurements.

---

## Repository Structure

```text
cn-project-18-online-exam-sdn/
│
├── README.md
├── requirements.txt
│
├── app/
│   ├── __init__.py
│   ├── server.py
│   ├── client.py
│   ├── protocol.py
│   └── questions.json
│
├── mininet/
│   └── topology.py
│
├── controller/
│   ├── controller.py
│   └── static_controller.py
│
├── experiments/
│   ├── generate_traffic.sh
│   ├── run_benchmarks.py
│   └── plot_results.py
│
├── results/
│   ├── raw/
│   └── figures/
│
└── docs/
    ├── architecture.md
    └── viva_notes.md
```

---

## Team Responsibilities

The project is divided into three technical workstreams.

| Member   | Responsibility                                | Components                                             |
| -------- | --------------------------------------------- | ------------------------------------------------------ |
| Member 1 | Application Development                       | TCP Server, Client, Protocol, Question Bank            |
| Member 2 | Infrastructure & SDN                          | Mininet Topology, Ryu Controller, Static Controller    |
| Member 3 | Systems Integration & Experimental Validation | Traffic Generation, Benchmarking, Performance Analysis |

Each member is responsible for maintaining their respective components and integrating their work into the central repository.

---

## Getting Started

### Prerequisites

* Ubuntu 20.04 / 22.04 LTS
* Python 3
* Mininet 2.3.0+
* Open vSwitch
* Ryu Controller
* iPerf
* Git

### Clone the Repository

```bash
git clone https://github.com/<GITHUB_USERNAME>/cn-project-18-online-exam-sdn.git

cd cn-project-18-online-exam-sdn
```

### Project Setup

Install the required dependencies after the project environment and dependency list have been finalized.

```bash
pip3 install -r requirements.txt
```

The complete execution procedure, including controller initialization, Mininet topology deployment, application startup and benchmarking, will be documented as the implementation progresses.

---

## Project Status

**Development in Progress**

The project is being developed collaboratively across three workstreams:

* TCP-based examination application.
* Mininet infrastructure and dynamic SDN controller.
* System integration and experimental validation.

Implementation, testing and performance evaluation are ongoing.

---

## Academic Information

**Project:** Computer Networks — Project 18
**Title:** Online Examination Network over SDN
**Domain:** Computer Networks and Software-Defined Networking
**Institution:** PES University

---

## License

This repository is intended for academic and educational purposes.
