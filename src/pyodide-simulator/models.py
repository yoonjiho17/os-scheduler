from dataclasses import dataclass, field
from typing import Literal

@dataclass
class Process:
    pid: str
    arrival_time: int
    burst_time: int


@dataclass
class DietProcess(Process):
    # DIET 전용 프로세스: 프론트에서 받은 식탐(appetite)을 tick별 I/O interrupt 확률로 보존한다.
    appetite: int
    # DIET의 기본 스케줄링 우선순위이며, ready 대기/CPU 하차 규칙에 따라 변한다.
    priority: float = 0.0
    # I/O interrupt 이후 ready queue에 복귀한 프로세스에 1틱 동안만 주는 진입 보너스다.
    enter_bonus: float = 0.0
    # enter_bonus를 제거하기까지 남은 tick 수다.
    enter_bonus_ticks: int = 0
    # 4초 이상 연속 실행으로 long decay가 적용됐는지 기록해 CPU 하차 감점 여부를 결정한다.
    long_decay_applied: bool = False


@dataclass
class ExecutionBlock:
    processor_id: str
    pid: str | None
    start_time: int
    end_time: int


@dataclass
class ProcessMetric:
    pid: str
    bt: int
    at: int
    tt: int
    wt: int
    ntt: float


@dataclass
class ReadyQueuePriority:
    pid: str
    priority: float
    enter_bonus: float
    score: float


@dataclass
class ReadyQueuePrioritySnapshot:
    time: int
    items: list[ReadyQueuePriority]


@dataclass
class ScheduleResult:
    timeline: list[ExecutionBlock]
    process_metrics: list[ProcessMetric]
    avg_wt: float
    avg_ntt: float
    total_energy: float
    max_time: int
    ready_queue_priorities: list[ReadyQueuePrioritySnapshot] = field(default_factory=list)


@dataclass
class Response:
    ok: bool
    data: dict | ScheduleResult | None
    error: dict | None


@dataclass
class Core:
    core_id: str
    core_type: Literal["P", "E"]


@dataclass
class Request:
    # 일반 요청은 appetite가 필요 없는 기존 스케줄링 알고리즘만 받는다.
    algorithm: Literal["fcfs", "rr", "hrrn", "spn", "srtn"]
    processes: list[Process]
    time_quantum: int | None
    cores: list[Core]


@dataclass
class DietRequest:
    # DIET 요청은 일반 Process가 아니라 appetite를 내장한 DietProcess만 받는다.
    algorithm: Literal["diet"]
    processes: list[DietProcess]
    time_quantum: int | None
    cores: list[Core]


@dataclass
class ProcessorRuntime:
    current_process: Process | None
    remaining_work: int
    start_time: int
    was_active_last_tick: bool
    elapsed_time: int


