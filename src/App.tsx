import { useEffect, useMemo, useState } from "react";
import Header from "./components/layout/Header";
import ProcessBox from "./components/ProcessBox";
import AlgorithmPanel from "./components/AlgorithmPanel";
import CoreBox from "./components/CoreBox";
import ResultTable from "./components/ResultTable";
import GanttChart from "./components/GanttChart";
import Modal from "./components/Modal";
import { defaultCores, defaultProcesses, type CoreUI, type ProcessUI } from "./state";
import { type AlgorithmId } from "./constants";
import { getPyodide, runSimulation, type ScheduleResult, type SimRequest } from "./pyodide";
import { deriveAtTick, useSimulationPlayback } from "./useSimulation";

export default function App() {
  const [pyodideReady, setPyodideReady] = useState(false);
  const [pyodideError, setPyodideError] = useState<string | null>(null);

  const [processes, setProcesses] = useState<ProcessUI[]>(() => defaultProcesses());
  const [cores, setCores] = useState<CoreUI[]>(() => defaultCores());
  const [algorithm, setAlgorithm] = useState<AlgorithmId>("rr");
  const [timeQuantum, setTimeQuantum] = useState(2);
  const [interval, setInterval] = useState(500);

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<ScheduleResult | null>(null);

  const [showResultModal, setShowResultModal] = useState(false);
  const [showGanttModal, setShowGanttModal] = useState(false);

  const playback = useSimulationPlayback({ result, intervalMs: interval });

  useEffect(() => {
    let mounted = true;
    getPyodide()
      .then(() => mounted && setPyodideReady(true))
      .catch((err) => mounted && setPyodideError(String(err)));
    return () => {
      mounted = false;
    };
  }, []);

  const onStart = async () => {
    setRunError(null);
    if (processes.length === 0) {
      setRunError("프로세스를 1개 이상 추가해주세요.");
      return;
    }
    const enabledCores = cores.filter((c) => c.enabled);
    if (enabledCores.length === 0) {
      setRunError("활성화된 CPU가 없어요.");
      return;
    }

    setRunning(true);
    try {
      const coresForRequest = enabledCores.map((c) => ({ core_id: c.coreId, core_type: c.coreType }));
      const request: SimRequest = algorithm === "diet"
        ? {
            algorithm,
            processes: processes.map((p) => ({
              pid: p.pid,
              arrival_time: p.arrivalTime,
              burst_time: p.burstTime,
              appetite: p.appetite,
            })),
            cores: coresForRequest,
            time_quantum: null,
          }
        : {
            algorithm,
            processes: processes.map((p) => ({
              pid: p.pid,
              arrival_time: p.arrivalTime,
              burst_time: p.burstTime,
            })),
            cores: coresForRequest,
            time_quantum: algorithm === "rr" ? timeQuantum : null,
          };
      const res = await runSimulation(request);
      if (!res.ok || !res.data) {
        setRunError(res.error?.message ?? "알 수 없는 오류");
        return;
      }
      setResult(res.data);
      playback.start(res.data);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const onReset = () => {
    playback.reset();
    setResult(null);
    setRunError(null);
  };

  const finished = playback.simState === "finished";
  const derived = useMemo(
    () => deriveAtTick(playback.tick, processes, result?.timeline ?? [], finished),
    [playback.tick, processes, result, finished],
  );
  const readySnapshot = useMemo(() => {
    if (algorithm !== "diet") return null;
    return result?.ready_queue_priorities.find((snapshot) => snapshot.time === playback.tick) ?? null;
  }, [algorithm, result, playback.tick]);

  const energy = result?.total_energy ?? 0;
  const metrics = result?.process_metrics ?? [];
  const maxTime = result?.max_time ?? 0;
  const readyPids = readySnapshot ? readySnapshot.items.map((item) => item.pid) : derived.readyPids;
  const readyPriorityByPid = new Map(readySnapshot?.items.map((item) => [item.pid, item.priority]) ?? []);

  if (!pyodideReady) {
    return (
      <div className="splash">
        <div className="splash__title">🐹 햄스터 깨우는 중...</div>
        <div className="splash__sub">
          {pyodideError ? `오류: ${pyodideError}` : "Pyodide를 불러오고 있어요"}
        </div>
        {!pyodideError && <div className="splash__bar" />}
      </div>
    );
  }

  const editsLocked = playback.simState === "running";

  return (
    <main className="app">
      <Header />

      <div className="layout-top">
        <div className="card combined-panel">
          <ProcessBox
            processes={processes}
            setProcesses={setProcesses}
            disabled={editsLocked}
            showAppetite={algorithm === "diet"}
          />
          <div className="combined-panel__divider" />
          <AlgorithmPanel
            algorithm={algorithm}
            setAlgorithm={setAlgorithm}
            timeQuantum={timeQuantum}
            setTimeQuantum={setTimeQuantum}
            interval={interval}
            setInterval={setInterval}
            simState={playback.simState}
            loading={running}
            onStart={onStart}
            onPause={playback.pause}
            onResume={playback.resume}
            onReset={onReset}
          />
        </div>
        <CoreBox
          algorithm={algorithm}
          cores={cores}
          setCores={setCores}
          processes={processes}
          runningByCore={derived.runningByCore}
          readyPids={readyPids}
          readyPriorityByPid={readyPriorityByPid}
          sleepPids={derived.sleepPids}
          simState={playback.simState}
          disabled={editsLocked}
        />
      </div>

      {runError && (
        <div className="card" style={{ borderColor: "#e89898", color: "#b95252" }}>
          ⚠ {runError}
        </div>
      )}

      <div className="layout-bottom">
        <ResultTable
          processes={processes}
          metrics={metrics}
          statusByPid={derived.statusByPid}
          energy={energy}
          onExpand={() => setShowResultModal(true)}
        />
        <GanttChart
          cores={cores}
          processes={processes}
          timeline={result?.timeline ?? []}
          currentTick={playback.tick}
          maxTime={maxTime}
          onExpand={() => setShowGanttModal(true)}
        />
      </div>

      <Modal title="프로세스 상태 요약" open={showResultModal} onClose={() => setShowResultModal(false)}>
        <ResultTable
          processes={processes}
          metrics={metrics}
          statusByPid={derived.statusByPid}
          energy={energy}
          expanded
        />
      </Modal>

      <Modal title="간트 차트" open={showGanttModal} onClose={() => setShowGanttModal(false)}>
        <GanttChart
          cores={cores}
          processes={processes}
          timeline={result?.timeline ?? []}
          currentTick={playback.tick}
          maxTime={maxTime}
          expanded
        />
      </Modal>
    </main>
  );
}
