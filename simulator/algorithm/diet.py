from collections import deque
import heapq
import random

from simulator.core_spec import CORE_SPECS
from simulator.models import (
    Core,
    DietProcess,
    ExecutionBlock,
    ProcessMetric,
    ProcessorRuntime,
    ReadyQueuePriority,
    ReadyQueuePrioritySnapshot,
    ScheduleResult,
)


class DIET:
    def __init__(self):
        self.total_energy = 0.0
        self.max_time = 0
        self.ready_wait_gain = 2
        self.enter_bonus_gain = 30
        self.running_bonus = 8
        self.long_run_threshold = 4
        self.long_run_decay = 0.85
        self.cpu_drop_decay = 0.75
        self.appetite_priority_weight = 10
        self.random_seed = 0
        self.random = random.Random(self.random_seed)

    def _score(self, process: DietProcess, running_bonus: float = 0.0) -> float:
        """DIET 스케줄링 점수: priority + enter_bonus + running_bonus."""
        return process.priority + process.enter_bonus + running_bonus

    def _ready_item(self, process: DietProcess) -> tuple[float, str, DietProcess]:
        # heapq는 최소 힙이므로 -score를 저장해 점수가 높은 프로세스가 먼저 나오게 한다.
        return -self._score(process), process.pid, process

    def _push_ready(self, ready_queue: list[tuple[float, str, DietProcess]], process: DietProcess) -> None:
        heapq.heappush(ready_queue, self._ready_item(process))

    def _rebuild_ready_queue(self, ready_queue: list[tuple[float, str, DietProcess]]) -> None:
        # ready 대기 중 priority/enter_bonus가 바뀌면 heap key도 바뀌므로 heap을 다시 만든다.
        ready_processes = [item[2] for item in ready_queue]
        ready_queue.clear()
        for process in ready_processes:
            self._push_ready(ready_queue, process)

    def _init_runtime(self, processes: list[DietProcess], cores: list[Core]):
        # priority는 DIET의 동적 점수이고, appetite는 초기 우선순위와 tick별 I/O interrupt 확률에 사용한다.
        for process in processes:
            process.priority = (process.appetite / 100.0) * self.appetite_priority_weight
            process.enter_bonus = 0.0
            process.enter_bonus_ticks = 0
            process.long_decay_applied = False

        remain_queue = deque(sorted(processes, key=lambda p: (p.arrival_time, p.pid)))
        ready_queue: list[tuple[float, str, DietProcess]] = []  # (-score, pid, diet_process)
        eating_queue: list[tuple[int, DietProcess]] = []  # (ready_time, diet_process)

        timeline: list[ExecutionBlock] = []
        completion_time: dict[str, int] = {}
        remaining_work: dict[str, int] = {process.pid: process.burst_time for process in processes}
        running_process: dict[str, DietProcess] = {}

        priority_cores = sorted(cores, key=lambda c: 0 if c.core_type == "P" else 1)
        runtime = {
            c.core_id: ProcessorRuntime(
                current_process=None,
                remaining_work=0,
                start_time=0,
                was_active_last_tick=False,
                elapsed_time=0,
            )
            for c in priority_cores
        }
        return (
            remain_queue,
            ready_queue,
            timeline,
            completion_time,
            priority_cores,
            runtime,
            eating_queue,
            remaining_work,
            running_process,
        )

    def _has_running_core(self, priority_cores: list[Core], runtime: dict[str, ProcessorRuntime]) -> bool:
        """현재 실행 중인 코어가 하나라도 있는지 확인한다."""
        for core in priority_cores:
            if runtime[core.core_id].current_process is not None:
                return True
        return False

    def _move_arrived(
            self,
            remain_queue: deque[DietProcess],
            ready_queue: list[tuple[float, str, DietProcess]],
            eating_queue: list[tuple[int, DietProcess]],
            time: int,
    ) -> None:
        """현재 시각까지 도착한 프로세스와 I/O 이후 복귀한 프로세스를 ready 큐로 이동한다."""
        while remain_queue and remain_queue[0].arrival_time <= time:
            self._push_ready(ready_queue, remain_queue.popleft())

        remaining_eating: list[tuple[int, DietProcess]] = []
        for ready_time, process in eating_queue:
            if ready_time <= time:
                # I/O interrupt로 ready 큐에 들어온 프로세스는 1틱 동안 enter_bonus를 받는다.
                process.enter_bonus = self.enter_bonus_gain
                process.enter_bonus_ticks = 1
                self._push_ready(ready_queue, process)
            else:
                remaining_eating.append((ready_time, process))
        eating_queue[:] = remaining_eating

    def _start_on_core(
            self,
            core_runtime: ProcessorRuntime,
            process: DietProcess,
            remaining_work: dict[str, int],
            time: int,
    ) -> None:
        """프로세스를 코어에 올리고, 이번 CPU 연속 실행 구간 상태를 초기화한다."""
        core_runtime.current_process = process
        core_runtime.remaining_work = remaining_work[process.pid]
        core_runtime.start_time = time
        core_runtime.elapsed_time = 0
        process.long_decay_applied = False

    def _apply_cpu_drop_penalty(self, process: DietProcess, caused_by_io: bool) -> None:
        """CPU에서 내려올 때 I/O나 long decay가 없었던 짧은 실행에는 priority 감점을 적용한다."""
        if caused_by_io or process.long_decay_applied:
            return
        process.priority *= self.cpu_drop_decay

    def _preempt_core(
            self,
            core: Core,
            runtime: dict[str, ProcessorRuntime],
            ready_queue: list[tuple[float, str, DietProcess]],
            timeline: list[ExecutionBlock],
            remaining_work: dict[str, int],
            running_process: dict[str, DietProcess],
            time: int,
    ) -> None:
        """선점된 프로세스의 실행 구간과 남은 작업을 저장한 뒤 ready 큐로 되돌린다."""
        core_runtime = runtime[core.core_id]
        process = running_process.pop(core.core_id)
        remaining_work[process.pid] = core_runtime.remaining_work

        if core_runtime.start_time < time:
            timeline.append(
                ExecutionBlock(
                    processor_id=core.core_id,
                    pid=process.pid,
                    start_time=core_runtime.start_time,
                    end_time=time,
                )
            )

        self._apply_cpu_drop_penalty(process, caused_by_io=False)
        self._push_ready(ready_queue, process)

    def _assign_to_cores(
            self,
            priority_cores: list[Core],
            runtime: dict[str, ProcessorRuntime],
            ready_queue: list[tuple[float, str, DietProcess]],
            timeline: list[ExecutionBlock],
            remaining_work: dict[str, int],
            running_process: dict[str, DietProcess],
            time: int,
    ) -> None:
        """비어 있는 코어를 채운 뒤, score 기준으로 필요한 선점을 수행한다."""
        # 1) 비어 있는 코어부터 ready 큐의 최고 score 프로세스로 채운다.
        for core in priority_cores:
            core_runtime = runtime[core.core_id]
            if core_runtime.current_process is None and ready_queue:
                _, _, process = heapq.heappop(ready_queue)
                self._start_on_core(core_runtime, process, remaining_work, time)
                running_process[core.core_id] = process

        # 2) ready 최고 score가 실행 중 프로세스의 score + running_bonus를 넘으면 선점한다.
        while ready_queue:
            candidate = ready_queue[0][2]
            candidate_score = self._score(candidate)
            preempt_core = None
            preempt_score = None

            for core in priority_cores:
                core_runtime = runtime[core.core_id]
                if core_runtime.current_process is None or core.core_id not in running_process:
                    continue

                current_process = running_process[core.core_id]
                current_score = self._score(current_process, self.running_bonus)
                if candidate_score > current_score and (preempt_score is None or current_score < preempt_score):
                    preempt_core = core
                    preempt_score = current_score

            if preempt_core is None:
                break

            self._preempt_core(preempt_core, runtime, ready_queue, timeline, remaining_work, running_process, time)
            _, _, process = heapq.heappop(ready_queue)
            preempt_runtime = runtime[preempt_core.core_id]
            self._start_on_core(preempt_runtime, process, remaining_work, time)
            preempt_runtime.was_active_last_tick = False
            running_process[preempt_core.core_id] = process

    def _tick_execute(
            self,
            priority_cores: list[Core],
            runtime: dict[str, ProcessorRuntime],
            timeline: list[ExecutionBlock],
            completion_time: dict[str, int],
            remaining_work: dict[str, int],
            running_process: dict[str, DietProcess],
            eating_queue: list[tuple[int, DietProcess]],
            time: int,
    ) -> None:
        """각 코어를 1초 실행하고, I/O interrupt/long decay/완료 처리/에너지 누적을 수행한다."""
        for core in priority_cores:
            core_runtime = runtime[core.core_id]
            process = core_runtime.current_process
            if process is None:
                core_runtime.was_active_last_tick = False
                continue

            core_spec = CORE_SPECS[core.core_type]
            tick_energy = core_spec["run_power"]
            if not core_runtime.was_active_last_tick:
                tick_energy += core_spec["startup_power"]
            self.total_energy += tick_energy

            processed_work = min(core_runtime.remaining_work, core_spec["speed"])
            core_runtime.remaining_work -= processed_work
            remaining_work[process.pid] = core_runtime.remaining_work
            core_runtime.was_active_last_tick = True
            core_runtime.elapsed_time += 1

            if (
                    isinstance(process, DietProcess)
                    and core_runtime.elapsed_time >= self.long_run_threshold
                    and not process.long_decay_applied
            ):
                # CPU 연속 실행이 4초 이상이면 priority를 낮추고, 하차 시 추가 감점은 면제한다.
                process.priority *= self.long_run_decay
                process.long_decay_applied = True

            if core_runtime.remaining_work == 0:
                finished_at = time + 1
                timeline.append(
                    ExecutionBlock(
                        processor_id=core.core_id,
                        pid=process.pid,
                        start_time=core_runtime.start_time,
                        end_time=finished_at,
                    )
                )
                completion_time[process.pid] = finished_at
                running_process.pop(core.core_id, None)
                core_runtime.current_process = None
                core_runtime.was_active_last_tick = False
                core_runtime.elapsed_time = 0
                continue

            if isinstance(process, DietProcess) and self.random.random() < (process.appetite / 100.0):
                interrupted_at = time + 1
                timeline.append(
                    ExecutionBlock(
                        processor_id=core.core_id,
                        pid=process.pid,
                        start_time=core_runtime.start_time,
                        end_time=interrupted_at,
                    )
                )
                remaining_work[process.pid] = core_runtime.remaining_work
                running_process.pop(core.core_id, None)
                # I/O는 1초 고정이며, 대기가 끝난 tick 시작에 ready 큐로 복귀해 바로 재할당될 수 있다.
                io_finished_at = interrupted_at + 1
                eating_queue.append((io_finished_at, process))
                timeline.append(
                    ExecutionBlock(
                        processor_id="eating_queue",
                        pid=process.pid,
                        start_time=interrupted_at,
                        end_time=io_finished_at,
                    )
                )
                core_runtime.current_process = None
                core_runtime.was_active_last_tick = False
                core_runtime.elapsed_time = 0

    def _age_ready_queue(
            self,
            ready_queue: list[tuple[float, str, DietProcess]],
            processes: list[DietProcess],
    ) -> None:
        """1틱 동안 ready 큐에 남아 있던 프로세스의 priority를 올리고 enter_bonus를 만료한다."""
        ready_processes = [item[2] for item in ready_queue]
        for process in ready_processes:
            process.priority += self.ready_wait_gain

        for process in processes:
            if process.enter_bonus_ticks > 0:
                process.enter_bonus_ticks -= 1
                if process.enter_bonus_ticks == 0:
                    process.enter_bonus = 0.0

        self._rebuild_ready_queue(ready_queue)

    def _record_ready_queue_priorities(
            self,
            ready_queue_priorities: list[ReadyQueuePrioritySnapshot],
            ready_queue: list[tuple[float, str, DietProcess]],
            time: int,
    ) -> None:
        ready_processes = sorted((item[2] for item in ready_queue), key=lambda p: (-self._score(p), p.pid))
        ready_queue_priorities.append(
            ReadyQueuePrioritySnapshot(
                time=time,
                items=[
                    ReadyQueuePriority(
                        pid=process.pid,
                        priority=process.priority,
                        enter_bonus=process.enter_bonus,
                        score=self._score(process),
                    )
                    for process in ready_processes
                ],
            )
        )

    def _build_result(
            self,
            processes: list[DietProcess],
            timeline: list[ExecutionBlock],
            completion_time: dict[str, int],
            ready_queue_priorities: list[ReadyQueuePrioritySnapshot],
    ) -> ScheduleResult:
        """FCFS와 같은 방식으로 TT/WT/NTT 메트릭과 결과를 만든다."""
        service_ticks: dict[str, int] = {}
        for block in timeline:
            if block.pid is None or block.processor_id == "eating_queue":
                continue
            service_ticks[block.pid] = service_ticks.get(block.pid, 0) + (block.end_time - block.start_time)

        process_metrics: list[ProcessMetric] = []
        total_wt = 0.0
        total_ntt = 0.0
        for process in sorted(processes, key=lambda x: x.pid):
            at = process.arrival_time
            tt = max(0.0, float(completion_time[process.pid] - at))
            service_time = float(service_ticks.get(process.pid, 0))
            wt = max(0.0, tt - service_time)
            ntt = tt / service_time if service_time > 0 else 0.0
            total_wt += wt
            total_ntt += ntt
            process_metrics.append(ProcessMetric(pid=process.pid, at=at, tt=tt, wt=wt, ntt=ntt))

        process_count = len(processes)
        avg_wt = total_wt / process_count if process_count else 0.0
        avg_ntt = total_ntt / process_count if process_count else 0.0

        return ScheduleResult(
            timeline=timeline,
            process_metrics=process_metrics,
            avg_wt=avg_wt,
            avg_ntt=avg_ntt,
            total_energy=self.total_energy,
            max_time=self.max_time,
            ready_queue_priorities=ready_queue_priorities,
        )

    def run(self, processes: list[DietProcess], cores: list[Core]) -> ScheduleResult:
        """DIET tick 루프를 실행하고 ScheduleResult를 반환한다."""
        self.random = random.Random(self.random_seed)
        (
            remain_queue,
            ready_queue,
            timeline,
            completion_time,
            priority_cores,
            runtime,
            eating_queue,
            remaining_work,
            running_process,
        ) = self._init_runtime(processes, cores)

        time = 0
        self.total_energy = 0.0
        ready_queue_priorities: list[ReadyQueuePrioritySnapshot] = []

        while True:
            has_running_core = self._has_running_core(priority_cores, runtime)
            if not (remain_queue or ready_queue or eating_queue or has_running_core):
                break

            self._move_arrived(remain_queue, ready_queue, eating_queue, time)
            self._assign_to_cores(priority_cores, runtime, ready_queue, timeline, remaining_work, running_process, time)
            self._record_ready_queue_priorities(ready_queue_priorities, ready_queue, time)
            self._tick_execute(
                priority_cores,
                runtime,
                timeline,
                completion_time,
                remaining_work,
                running_process,
                eating_queue,
                time,
            )
            self._age_ready_queue(ready_queue, processes)
            time += 1

        self.max_time = time
        return self._build_result(processes, timeline, completion_time, ready_queue_priorities)
