from collections import deque

from simulator.core_spec import CORE_SPECS
from simulator.models import Core, ExecutionBlock, Process, ProcessMetric, ProcessorRuntime, ScheduleResult


class RR:
    def __init__(self):
        self.total_energy = 0.0
        self.max_time = 0

    def _init_runtime(self, processes: list[Process], cores: list[Core]):
        remain_queue = deque(sorted(processes, key=lambda p: (p.arrival_time, p.pid)))
        ready_queue: deque[Process] = deque([])
        timeline: list[ExecutionBlock] = []
        completion_time: dict[str, int] = {}
        remaining_work_by_pid = {process.pid: process.burst_time for process in processes}

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

        time_slice_used = {c.core_id: 0 for c in priority_cores}

        return (
            remain_queue,
            ready_queue,
            timeline,
            completion_time,
            remaining_work_by_pid,
            priority_cores,
            runtime,
            time_slice_used,
        )

    def _has_running_core(self, priority_cores: list[Core], runtime: dict) -> bool:
        return any(runtime[c.core_id].current_process is not None for c in priority_cores)

    def _move_arrived(self, remain_queue: deque, ready_queue: deque[Process], time: int) -> None:
        while remain_queue and remain_queue[0].arrival_time <= time:
            ready_queue.append(remain_queue.popleft())

    def _assign_to_idle_cores(
        self,
        priority_cores: list[Core],
        runtime: dict,
        ready_queue: deque[Process],
        time: int,
        time_slice_used: dict,
        remaining_work_by_pid: dict[str, int],
    ) -> None:
        for core in priority_cores:
            core_runtime = runtime[core.core_id]

            if core_runtime.current_process is None and ready_queue:
                process = ready_queue.popleft()

                core_runtime.current_process = process
                core_runtime.remaining_work = remaining_work_by_pid[process.pid]
                core_runtime.start_time = time
                core_runtime.elapsed_time = 0

                time_slice_used[core.core_id] = 0

    def _tick_execute(
        self,
        priority_cores: list[Core],
        runtime: dict,
        timeline: list[ExecutionBlock],
        completion_time: dict[str, int],
        time: int,
        time_quantum: int,
        ready_queue: deque,
        time_slice_used: dict,
        remaining_work_by_pid: dict[str, int],
    ) -> None:

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

            processable = core_spec["speed"]
            processed = min(core_runtime.remaining_work, processable)

            core_runtime.remaining_work -= processed
            remaining_work_by_pid[process.pid] = core_runtime.remaining_work
            core_runtime.elapsed_time += 1
            time_slice_used[core.core_id] += 1

            core_runtime.was_active_last_tick = True

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
                remaining_work_by_pid[process.pid] = 0

                core_runtime.current_process = None
                core_runtime.remaining_work = 0
                core_runtime.elapsed_time = 0
                time_slice_used[core.core_id] = 0
                core_runtime.was_active_last_tick = False

            elif time_slice_used[core.core_id] >= time_quantum:
                timeline.append(
                    ExecutionBlock(
                        processor_id=core.core_id,
                        pid=process.pid,
                        start_time=core_runtime.start_time,
                        end_time=time + 1,
                    )
                )

                ready_queue.append(process)

                core_runtime.current_process = None
                core_runtime.remaining_work = 0
                core_runtime.start_time = 0
                core_runtime.was_active_last_tick = False
                time_slice_used[core.core_id] = 0

    def _build_result(
        self,
        processes: list[Process],
        timeline: list[ExecutionBlock],
        completion_time: dict[str, int],
    ) -> ScheduleResult:

        calc_bt: dict[str, int] = {p.pid: 0 for p in processes}
        for block in timeline:
            if block.pid is None:
                continue
            calc_bt[block.pid] += block.end_time - block.start_time

        process_metrics = []
        total_wt = 0.0
        total_ntt = 0.0

        for p in sorted(processes, key=lambda x: x.pid):
            tt = max(0, completion_time[p.pid] - p.arrival_time)
            bt = calc_bt[p.pid]
            wt = max(0, tt - bt)
            ntt = tt / bt if bt > 0 else 0.0

            total_wt += wt
            total_ntt += ntt

            process_metrics.append(
                ProcessMetric(pid=p.pid, bt=bt, at=p.arrival_time, tt=tt, wt=wt, ntt=ntt)
            )

        n = len(processes)

        return ScheduleResult(
            timeline=timeline,
            process_metrics=process_metrics,
            avg_wt=total_wt / n if n else 0.0,
            avg_ntt=total_ntt / n if n else 0.0,
            total_energy=self.total_energy,
            max_time=self.max_time,
        )

    def run(self, processes: list[Process], cores: list[Core], time_quantum: int) -> ScheduleResult:

        (
            remain_queue,
            ready_queue,
            timeline,
            completion_time,
            remaining_work_by_pid,
            priority_cores,
            runtime,
            time_slice_used,
        ) = self._init_runtime(processes, cores)

        time = 0
        self.total_energy = 0.0

        while True:
            has_running = self._has_running_core(priority_cores, runtime)
            if not (remain_queue or ready_queue or has_running):
                break

            self._move_arrived(remain_queue, ready_queue, time)

            self._assign_to_idle_cores(
                priority_cores, runtime, ready_queue, time, time_slice_used, remaining_work_by_pid
            )

            self._tick_execute(
                priority_cores,
                runtime,
                timeline,
                completion_time,
                time,
                time_quantum,
                ready_queue,
                time_slice_used,
                remaining_work_by_pid,
            )

            time += 1

        self.max_time = time

        return self._build_result(processes, timeline, completion_time)
