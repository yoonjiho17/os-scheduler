import { CPU_COLORS, PROCESS_COLORS, READY_QUEUE_VISIBLE, type AlgorithmId } from "../constants";
import type { CoreUI, ProcessUI } from "../state";
import type { SimState } from "./AlgorithmPanel";
import Hamster from "./Hamster";
import hamsterSeedImg from "../asset/HamsterSeed.png";

interface CoreBoxProps {
  algorithm: AlgorithmId;
  cores: CoreUI[];
  setCores: (next: CoreUI[]) => void;
  processes: ProcessUI[];
  runningByCore: Map<string, string>;
  readyPids: string[];
  readyPriorityByPid: Map<string, number>;
  sleepPids: string[];
  simState: SimState;
  disabled: boolean;
}

export default function CoreBox(props: CoreBoxProps) {
  const { cores, setCores, processes, runningByCore, readyPids, readyPriorityByPid, sleepPids, simState, disabled } = props;

  const procByPid = new Map(processes.map((p) => [p.pid, p]));

  const updateCore = (idx: number, patch: Partial<CoreUI>) => {
    setCores(cores.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };

  const visibleReady = readyPids.slice(0, READY_QUEUE_VISIBLE);
  const overflow = Math.max(0, readyPids.length - READY_QUEUE_VISIBLE);

  return (
    <section className="card">
      <div className="card__title">
        <span aria-hidden>🐹</span>
        <span>프로세서 (CPU)</span>
      </div>

      <div className="cpu-row">
        {cores.map((c, idx) => {
          const cpuColor = CPU_COLORS[c.colorIdx % CPU_COLORS.length];
          const runningPid = runningByCore.get(c.coreId);
          const runningProc = runningPid ? procByPid.get(runningPid) : undefined;
          const isRunning = simState === "running" && Boolean(runningProc);
          const wheelColor = runningProc
            ? PROCESS_COLORS[runningProc.colorIdx % PROCESS_COLORS.length]
            : cpuColor;

          return (
            <div key={c.coreId} className={`cpu ${c.enabled ? "" : "cpu--off"} ${isRunning ? "cpu--running" : ""}`}>
              <div className="cpu__label" style={{ color: cpuColor.pill }}>CPU {idx + 1}</div>
              <div
                className="cpu__wheel"
                style={{ borderColor: cpuColor.border }}
              >
                <div className="cpu__wheel-bg" style={{ background: cpuColor.bg }} />
                <div className="cpu__wheel-inner">
                  {runningProc && (
                    <Hamster
                      bg={wheelColor.bg}
                      border={wheelColor.border}
                      size={120}
                      variant="run"
                    />
                  )}
                </div>
                <span className="cpu__num">{idx + 1}</span>
              </div>

              <div className="cpu__controls">
                <span className="toggle">
                  <button
                    className={c.coreType === "P" ? "active" : ""}
                    disabled={disabled}
                    onClick={() => updateCore(idx, { coreType: "P" })}
                  >P</button>
                  <button
                    className={c.coreType === "E" ? "active" : ""}
                    disabled={disabled}
                    onClick={() => updateCore(idx, { coreType: "E" })}
                  >E</button>
                </span>
                <button
                  className={`power-btn ${c.enabled ? "on" : ""}`}
                  disabled={disabled}
                  onClick={() => updateCore(idx, { enabled: !c.enabled })}
                  title={c.enabled ? "사용 중" : "꺼짐"}
                >
                  {c.enabled ? "ON" : "OFF"}
                </button>
              </div>

              <div className="cpu__process-name">
                {runningProc ? `${runningProc.pid} · ${runningProc.name}` : ""}
              </div>
            </div>
          );
        })}
      </div>

      <div className="queue-row">
        <div className="queue">
          <div className="queue__title">Ready Queue (대기 중)</div>
          <div className="queue__cells">
            {Array.from({ length: READY_QUEUE_VISIBLE }).map((_, i) => {
              const pid = visibleReady[i];
              const proc = pid ? procByPid.get(pid) : undefined;
              const color = proc ? PROCESS_COLORS[proc.colorIdx % PROCESS_COLORS.length] : null;
              return (
                <div key={i} className={`queue__cell ${proc ? "" : "queue__cell--empty"}`}>
                  {proc && color ? (
                    <>
                      <Hamster
                        bg={color.bg}
                        border={color.border}
                        size={32}
                        variant={
                          algorithm === "diet"
                            ? "diet-ready"
                            : (readyPriorityByPid.get(proc.pid) ?? 0) >= 60
                              ? "fat"
                              : "idle"
                        }
                      />
                      <span className="pid-pill" style={{ background: color.pill }}>{proc.pid}</span>
                    </>
                  ) : null}
                </div>
              );
            })}
            {overflow > 0 && <span className="queue__more">+{overflow}</span>}
          </div>
        </div>

        <div className="sleep">
          <div className="queue__title">Sleep (I/O 대기 중)</div>
          <div className="sleep__cells">
            {sleepPids.length === 0 ? (
              <span className="sleep__empty">씨앗을 먹는 햄스터가 없어요</span>
            ) : (
              sleepPids.map((pid) => {
                const proc = procByPid.get(pid);
                if (!proc) return null;
                const color = PROCESS_COLORS[proc.colorIdx % PROCESS_COLORS.length];
                return (
                  <span key={pid} style={{ display: "inline-flex", alignItems: "center" }}>
                    <Hamster 
                      bg={color.bg} 
                      border={color.border} 
                      size={34} 
                      variant={algorithm === "diet" ? "diet-sleep" : "sleep"} 
                    />
                    {algorithm !== "diet" && <img src={hamsterSeedImg} alt="seed" className="sleep__seed-img" />}
                  </span>
                );
              })
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

