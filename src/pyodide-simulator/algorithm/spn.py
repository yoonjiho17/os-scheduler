from collections import deque

from simulator.core_spec import CORE_SPECS
from simulator.models import Core, ExecutionBlock, Process, ProcessMetric, ProcessorRuntime, ScheduleResult


class SPN:
    def __init__(self):
        """전체 시뮬레이션 누적 에너지와 완료 시각을 초기화"""
        self.total_energy = 0.0
        self.max_time = 0

    def _init_runtime(self, processes: list[Process], cores: list[Core]):
        """
                입력 프로세스/코어를 시뮬레이션 런타임 상태로 초기화
                remain_queue: 아직 도착하지 않은 작업
                ready_queue: 도착해서 실행 대기 중인 작업(FIFO)
                timeline: 렌더링용 실행 블록 결과
                completion_time: pid별 완료 시각(메트릭 계산용)
                priority_cores: 같은 시각에는 P 코어를 먼저 배정
                runtime: 코어별 현재 실행 상태
                """
        remain_queue = deque(sorted(processes, key=lambda p: (p.arrival_time, p.pid)))
        ready_queue: deque[Process] = deque([])
        timeline: list[ExecutionBlock] = []
        completion_time: dict[str, int] = {}
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
        return remain_queue, ready_queue, timeline, completion_time, priority_cores, runtime

    def _has_running_core(self, priority_cores: list[Core], runtime: dict) -> bool:
        """현재 실행 중인 코어가 하나라도 있는지 확인"""
        for core in priority_cores:
            if runtime[core.core_id].current_process is not None:
                return True
        return False

    def _move_arrived(self, remain_queue: deque, ready_queue: deque[Process], time: int) -> None:
        """현재 시각까지 도착한 프로세스를 준비 큐로 이동 및 ready_queue의 프로세스들을 burst_time 순으로 정렬"""
        while remain_queue and remain_queue[0].arrival_time <= time:
            ready_queue.append(remain_queue.popleft())
        sorted_processes = deque(sorted(ready_queue, key=lambda p: p.burst_time))
        ready_queue.clear()
        ready_queue.extend(sorted_processes)

    def _assign_to_idle_cores(
        self,
        priority_cores: list[Core],
        runtime: dict,
        ready_queue: deque[Process],
        time: int,
    ) -> None:
        """Idle 코어에 SPN 순서대로 프로세스를 할당"""
        for core in priority_cores:
            core_runtime = runtime[core.core_id]
            if core_runtime.current_process is None and ready_queue:
                process = ready_queue.popleft()
                core_runtime.current_process = process
                core_runtime.remaining_work = process.burst_time
                core_runtime.start_time = time
                core_runtime.elapsed_time = 0

    def _tick_execute(
        self,
        priority_cores: list[Core],
        runtime: dict,
        timeline: list[ExecutionBlock],
        completion_time: dict[str, int],
        time: int,
    ) -> None:
        """
                각 코어를 1초 실행
                1) 동작 전력 + 필요 시 시동 전력 반영
                2) 남은 일 감소
                3) 완료 시 timeline/completion_time 기록
                """
        for core in priority_cores:
            core_runtime = runtime[core.core_id]
            process = core_runtime.current_process
            if process is None:
                # 실행 중인 작업이 없으면 이번 tick은 비활성 상태
                core_runtime.was_active_last_tick = False
                continue

            core_spec = CORE_SPECS[core.core_type]
            # 실행 중에는 동작 전력 소모
            tick_energy = core_spec["run_power"]
            # 직전 tick이 idle이면 이번 tick 시작 시 시동 전력 추가
            if not core_runtime.was_active_last_tick:
                tick_energy += core_spec["startup_power"]
            self.total_energy += tick_energy

            # 이번 1초에 처리 가능한 일 양 계산
            processable_work = core_spec["speed"]
            remaining_work = core_runtime.remaining_work
            if remaining_work <= processable_work:
                processed_work = remaining_work
            else:
                processed_work = processable_work

            # 남은 일 업데이트
            core_runtime.remaining_work = remaining_work - processed_work
            core_runtime.was_active_last_tick = True
            core_runtime.elapsed_time += 1

            # 작업이 끝나면 timeline/completion_time 기록 후 코어 비움
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
                core_runtime.current_process = None
                core_runtime.was_active_last_tick = False
                core_runtime.elapsed_time = 0

    def _build_result(
        self,
        processes: list[Process],
        timeline: list[ExecutionBlock],
        completion_time: dict[str, int],
    ) -> ScheduleResult:
        """
                완료 시각 기준으로 프로세스 메트릭을 계산해 결과를 생성
                TT = completion - arrival
                WT = max(0, TT - burst)
                NTT = max(1, TT / burst)
                """
        calc_bt: dict[str, int] = {p.pid: 0 for p in processes}
        for block in timeline:
            if block.pid is None:
                continue
            calc_bt[block.pid] += block.end_time - block.start_time

        process_metrics: list[ProcessMetric] = []
        total_wt = 0.0
        total_ntt = 0.0
        for process in sorted(processes, key=lambda x: x.pid):
            at = process.arrival_time
            tt = max(0, completion_time[process.pid] - at)
            bt = calc_bt[process.pid]
            wt = max(0, tt - bt)
            ntt = tt / bt if bt > 0 else 0.0
            total_wt += wt
            total_ntt += ntt
            process_metrics.append(ProcessMetric(pid=process.pid, bt=bt, at=at, tt=tt, wt=wt, ntt=ntt))

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
        )

    def run(self, processes: list[Process], cores: list[Core]) -> ScheduleResult:
        """SPN tick 루프를 실행하고 ScheduleResult를 반환"""
        (
            remain_queue,
            ready_queue,
            timeline,
            completion_time,
            priority_cores,
            runtime,
        ) = self._init_runtime(processes, cores)

        time = 0
        self.total_energy = 0.0

        while True:
            # 반복 종료 조건: 미래 작업/대기 작업/실행 작업이 모두 없으면 종료
            has_running_core = self._has_running_core(priority_cores, runtime)
            if not (remain_queue or ready_queue or has_running_core):
                break

            # 1) 도착한 작업 이동
            self._move_arrived(remain_queue, ready_queue, time)
            # 2) idle 코어에 할당
            self._assign_to_idle_cores(priority_cores, runtime, ready_queue, time)
            # 3) 1초 실행
            self._tick_execute(priority_cores, runtime, timeline, completion_time, time)
            # 4) 다음 tick
            time += 1

        # 전체 완료 시각 저장
        self.max_time = time
        return self._build_result(processes, timeline, completion_time)
