import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  Activity,
  ArrowRight,
  CalendarSearch,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  FileSpreadsheet,
  FolderOpen,
  Layers3,
  LoaderCircle,
  Menu,
  Moon,
  Play,
  Radio,
  Search,
  ShieldCheck,
  Square,
  Sun,
  Terminal,
  Unplug,
  X,
  Zap,
} from "lucide-react";
import {
  dateTime,
  departments,
  emptyState,
  errorMessage,
  loadPreferences,
  preferenceKey,
} from "./api";
import type { Bridge, JobState, Operation, Options, Preferences } from "./api";
import Results from "./Results";

type Tab = Operation;
type Notice = { kind: "success" | "error"; message: string };
const tabs = [
  {
    id: "batch",
    label: "Extração em lote",
    icon: Layers3,
  },
  {
    id: "single",
    label: "Consulta rápida",
    icon: Search,
  },
  {
    id: "schedule",
    label: "Localizar programação",
    icon: CalendarSearch,
  },
  {
    id: "monitor",
    label: "Monitoramento",
    icon: Radio,
  },
] as const;
const statusLabels: Record<JobState["status"], string> = {
  idle: "Pronto para começar",
  running: "Em execução",
  waiting: "Aguardando próximo ciclo",
  completed: "Concluído",
  cancelled: "Cancelado",
  error: "Falha na operação",
};
const phaseLabels: Record<string, string> = {
  starting: "Preparando a operação.",
  status:
    "Consultando os status dos desligamentos. Os motivos, quando solicitados, serão consultados em seguida.",
  reasons:
    "Consultando os motivos de negação. A consulta de status terminou, mas a operação ainda não foi concluída.",
  schedule:
    "Localizando programações pelos filtros informados no período selecionado. Aguarde o retorno da consulta.",
  waiting: "Ciclo concluído. Aguardando a próxima execução automática.",
  completed: "Todas as etapas da operação foram concluídas.",
  cancelled: "A operação foi cancelada.",
  error:
    "A operação encontrou um erro. Consulte a mensagem e o registro de atividade.",
  idle: "Aguardando o início de uma operação.",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("batch");
  const [mobileNav, setMobileNav] = useState(false);
  const sidebar = useRef<HTMLElement>(null);
  const [bridge, setBridge] = useState<Bridge | null>(
    () => window.pywebview?.api ?? null,
  );
  const [state, setState] = useState<JobState>(emptyState);
  const [synced, setSynced] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [preferences, setPreferences] = useState<Preferences>(loadPreferences);
  const [storageError, setStorageError] = useState("");
  const [number, setNumber] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [company, setCompany] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const pendingRef = useRef(false);
  const [awaitingStart, setAwaitingStart] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [logsOpen, setLogsOpen] = useState(false);
  const stateRequest = useRef<Promise<JobState> | null>(null);
  const revision = useRef(0);
  const refresh = useRef<() => void>(() => {});
  const activeTab = tabs.find((item) => item.id === tab)!;
  const active = state.status === "running" || state.status === "waiting";
  const locked = active || awaitingStart || pending !== null;
  const available = !!bridge && synced && !connectionError;
  const canExport =
    available &&
    !awaitingStart &&
    pending === null &&
    state.rows.length > 0 &&
    (!active || (state.operation === "monitor" && state.status === "waiting"));
  const indeterminate = state.phase === "reasons" || state.phase === "schedule";
  const progressLabel =
    state.phase === "reasons"
      ? "Progresso dos motivos"
      : state.phase === "schedule"
        ? "Progresso da busca"
        : state.phase === "status"
          ? "Progresso dos status"
          : "Progresso da operação";
  const progress =
    state.total > 0
      ? Math.min(
          100,
          Math.max(0, Math.round((state.completed / state.total) * 100)),
        )
      : 0;

  useEffect(() => {
    if (!mobileNav) return;
    const previous = document.activeElement;
    const buttons =
      sidebar.current?.querySelectorAll<HTMLButtonElement>("button");
    buttons?.[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNav(false);
      if (event.key !== "Tab" || !buttons?.length) return;
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [mobileNav]);

  useEffect(() => {
    const ready = () => setBridge(window.pywebview?.api ?? null);
    window.addEventListener("pywebviewready", ready);
    ready();
    return () => window.removeEventListener("pywebviewready", ready);
  }, []);

  useEffect(() => {
    if (!bridge) return;
    let disposed = false;
    let inFlight = false;
    let requested = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (disposed) return;
      if (inFlight) {
        requested = true;
        return;
      }
      clearTimeout(timer);
      inFlight = true;
      const currentRevision = revision.current;
      try {
        // Reutiliza a leitura pendente quando o efeito reinicia.
        if (!stateRequest.current)
          stateRequest.current = bridge.get_state().finally(() => {
            stateRequest.current = null;
          });
        const next = await stateRequest.current;
        if (
          !next ||
          !(next.status in statusLabels) ||
          !Array.isArray(next.rows) ||
          !Array.isArray(next.logs)
        )
          throw new Error(
            "Resposta de estado inválida recebida do aplicativo.",
          );
        if (!disposed && currentRevision === revision.current) {
          setState(next);
          setSynced(true);
          setConnectionError("");
          if (next.status !== "idle") setAwaitingStart(false);
        }
      } catch (error) {
        if (!disposed) setConnectionError(errorMessage(error));
      } finally {
        inFlight = false;
        if (!disposed) {
          timer = setTimeout(() => void poll(), requested ? 0 : 900);
          requested = false;
        }
      }
    };
    refresh.current = () => void poll();
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
      refresh.current = () => {};
    };
  }, [bridge]);

  useEffect(() => {
    try {
      localStorage.setItem(preferenceKey, JSON.stringify(preferences));
      setStorageError("");
    } catch {
      setStorageError(
        "Não foi possível salvar as preferências neste dispositivo. Os ajustes continuam válidos nesta sessão.",
      );
    }
  }, [preferences]);

  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute(
        "content",
        preferences.theme === "dark" ? "#0e151c" : "#10243a",
      );
  }, [preferences.theme]);

  function update<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setPreferences((current) => ({ ...current, [key]: value }));
  }
  async function action(
    name: string,
    callback: (api: Bridge) => Promise<void>,
  ) {
    if (!bridge || pendingRef.current) return;
    pendingRef.current = true;
    setPending(name);
    setNotice(null);
    try {
      await callback(bridge);
    } catch (error) {
      setNotice({ kind: "error", message: errorMessage(error) });
    } finally {
      pendingRef.current = false;
      setPending(null);
    }
  }
  async function selectInput() {
    await action("file", async (api) => {
      const result = await api.select_input();
      if (!result.ok) {
        if (result.error) throw new Error(result.error);
        return;
      }
      if (!result.input)
        throw new Error("O aplicativo não retornou os dados do arquivo.");
      revision.current += 1;
      setState((current) => ({ ...current, input: result.input! }));
      setNotice({
        kind: "success",
        message: `Arquivo ${result.input.name} selecionado.`,
      });
      refresh.current();
    });
  }
  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!available || locked) return;
    if ((tab === "batch" || tab === "monitor") && !state.input) {
      setNotice({
        kind: "error",
        message: "Selecione um arquivo de entrada antes de iniciar.",
      });
      return;
    }
    if (tab === "schedule" && startDate > endDate) {
      setNotice({
        kind: "error",
        message: "A data final deve ser igual ou posterior à data inicial.",
      });
      return;
    }
    if (tab === "single" && !number.trim()) {
      setNotice({
        kind: "error",
        message: "Informe o número do desligamento.",
      });
      return;
    }
    if (tab === "schedule") {
      if (!identifier.trim() && !company.trim()) {
        setNotice({
          kind: "error",
          message: "Informe uma OT/ORDEM ou uma empresa para localizar.",
        });
        return;
      }
      const normalizedCompany = company
        .normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .trim();
      if (
        company.trim() &&
        (!normalizedCompany ||
          [...company.trim()].some((character) => character.charCodeAt(0) < 32))
      ) {
        setNotice({
          kind: "error",
          message: "A empresa contém caracteres inválidos. Informe parte do nome.",
        });
        return;
      }
      // Valida o prefixo sem alterar o valor enviado ao localizador.
      const order = identifier
        .replace(/^\s*(?:OT|ORDEM)\s*[:#-]?\s*/i, "")
        .trim();
      if (
        (identifier.trim() && !order) ||
        [...order].some((character) => character.charCodeAt(0) < 32)
      ) {
        setNotice({
          kind: "error",
          message: !order
            ? "Informe uma OT ou ORDEM para localizar."
            : "A OT ou ORDEM contém caracteres inválidos.",
        });
        return;
      }
    }
    const options: Options = {
      operation: tab,
      include_reasons: preferences.include_reasons,
      number: number.trim(),
      department: preferences.department,
      identifier: identifier.trim(),
      company: company.trim(),
      start_date: startDate,
      end_date: endDate,
      interval_minutes: preferences.interval_minutes,
      delay: preferences.delay,
      timeout: preferences.timeout,
      reason_timeout: preferences.reason_timeout,
      attempts: preferences.attempts,
      debug: preferences.debug,
    };
    await action("start", async (api) => {
      const result = await api.start_job(options);
      if (!result.ok)
        throw new Error(result.error || "Não foi possível iniciar a operação.");
      revision.current += 1;
      setAwaitingStart(true);
      setNotice({
        kind: "success",
        message: "Operação aceita. Acompanhando o estado do aplicativo.",
      });
      refresh.current();
    });
  }
  async function cancel() {
    await action("cancel", async (api) => {
      const result = await api.cancel_job();
      if (!result.ok)
        throw new Error(
          result.error || "Não foi possível solicitar o cancelamento.",
        );
      revision.current += 1;
      setAwaitingStart(false);
      setNotice({
        kind: "success",
        message:
          "Cancelamento solicitado. Aguarde a confirmação no estado da operação.",
      });
      refresh.current();
    });
  }
  async function exportResults() {
    if (!canExport) return;
    await action("export", async (api) => {
      const result = await api.export_results();
      if (!result.ok)
        throw new Error(result.error || "A exportação não foi concluída.");
      setNotice({
        kind: "success",
        message: result.path
          ? `Excel exportado para ${result.path}`
          : "Resultados exportados com sucesso.",
      });
    });
  }

  const reasons = (
    <label className="checkbox-field">
      <input
        type="checkbox"
        checked={preferences.include_reasons}
        onChange={(e) => update("include_reasons", e.target.checked)}
      />
      <span>
        <strong>Incluir motivos de negação</strong>
        <small>Consulta os detalhes adicionais de cada desligamento.</small>
      </span>
    </label>
  );
  const filePicker = (
    <div className="file-input">
      <div className="file-picker">
        <div className="file-symbol">
          <FileSpreadsheet size={27} />
        </div>
        <div className="file-info">
          <strong>
            {state.input?.name || "Selecione seu arquivo de entrada"}
          </strong>
          <span>
            {state.input
              ? `${state.input.count.toLocaleString("pt-BR")} registros identificados`
              : "Escolha um arquivo pelo seletor do aplicativo desktop."}
          </span>
          {state.input && (
            <small title={state.input.path}>{state.input.path}</small>
          )}
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => void selectInput()}
          disabled={!available || locked}
        >
          <FolderOpen size={16} />
          {pending === "file"
            ? "Selecionando…"
            : state.input
              ? "Trocar arquivo"
              : "Escolher arquivo"}
        </button>
      </div>
      <aside
        className="file-format"
        aria-label="Estrutura do arquivo de entrada"
      >
        <div className="file-format-copy">
          <strong>Estrutura obrigatória do arquivo</strong>
          <p>
            Use CSV, XLS ou XLSX com uma coluna chamada exatamente{" "}
            <code>numero_desligamento</code>. Informe um número por linha,
            usando apenas dígitos. Outras colunas serão ignoradas.
          </p>
        </div>
        <table
          className="file-example"
          aria-label="Exemplo de arquivo de entrada"
        >
          <thead>
            <tr>
              <th>numero_desligamento</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>123456</td>
            </tr>
            <tr>
              <td>789012</td>
            </tr>
          </tbody>
        </table>
      </aside>
    </div>
  );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Ir para o conteúdo
      </a>
      {mobileNav && (
        <button
          className="nav-scrim"
          aria-label="Fechar navegação"
          onClick={() => setMobileNav(false)}
        />
      )}
      <aside
        ref={sidebar}
        className={`sidebar ${mobileNav ? "is-open" : ""}`}
        aria-label="Navegação principal"
      >
        <div className="brand">
          <span className="brand-icon">
            <Zap size={24} fill="currentColor" />
          </span>
          <div>
            <strong>Extrator SGD</strong>
          </div>
          <button
            className="mobile-close icon-button"
            aria-label="Fechar menu"
            onClick={() => setMobileNav(false)}
          >
            <X size={20} />
          </button>
        </div>
        <div className="workspace-label">
          <span className="workspace-dot" />
          EXTRATOR DE DESLIGAMENTOS
        </div>
        <span className="nav-label">ÁREA DE TRABALHO</span>
        <nav>
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${tab === id ? "selected" : ""}`}
              aria-current={tab === id ? "page" : undefined}
              onClick={() => {
                setTab(id);
                setMobileNav(false);
              }}
            >
              <Icon size={19} />
              <span>{label}</span>
              {tab === id && <span className="nav-marker" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button
            type="button"
            className="theme-toggle"
            aria-label={
              preferences.theme === "dark"
                ? "Ativar tema claro"
                : "Ativar tema escuro"
            }
            aria-pressed={preferences.theme === "dark"}
            onClick={() =>
              update("theme", preferences.theme === "dark" ? "light" : "dark")
            }
          >
            {preferences.theme === "dark" ? (
              <Sun size={18} />
            ) : (
              <Moon size={18} />
            )}
            <span>
              <strong>Tema escuro</strong>
              <small>
                {preferences.theme === "dark" ? "Ativado" : "Desativado"}
              </small>
            </span>
            <span className="theme-switch" aria-hidden="true">
              <span />
            </span>
          </button>
          <div className="desktop-note">
            <ShieldCheck size={21} />
            <strong>Necessario VPN</strong>
            <p>
              Qualquer operação a ser executada pelo aplicativo é efetuado
              apenas mediante conexão VPN para acesso a base
            </p>
          </div>
          <div className="sidebar-version">
            <span>Painel operacional</span>
            <span>v1.0</span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <main id="main" tabIndex={-1}>
          <span
            className="sr-only"
            data-testid="connection-status"
            aria-live="polite"
          >
            {!bridge
              ? "Modo visual"
              : connectionError
                ? "Conexão interrompida"
                : synced
                  ? "Desktop conectado"
                  : "Conectando…"}
          </span>
          <div className="page-heading">
            <div className="page-title">
              <button
                className="icon-button mobile-menu"
                aria-label="Abrir navegação"
                aria-expanded={mobileNav}
                onClick={() => setMobileNav(true)}
              >
                <Menu size={21} />
              </button>
              <h1>{activeTab.label}</h1>
            </div>
            <span className="page-symbol">
              <activeTab.icon size={31} strokeWidth={1.5} />
            </span>
          </div>
          {!bridge && (
            <div className="banner visual-banner">
              <Unplug size={20} />
              <div>
                <strong>Modo visual · aplicativo desktop não conectado</strong>
                <p>
                  Explore a interface e ajuste suas preferências. Seleção de
                  arquivos, consultas e exportação ficam disponíveis somente no
                  aplicativo com integração pywebview.
                </p>
              </div>
            </div>
          )}
          {connectionError && (
            <div className="banner error-banner" role="alert">
              <CircleAlert size={20} />
              <div>
                <strong>Não foi possível atualizar o estado</strong>
                <p>
                  {connectionError} Os dados exibidos podem estar
                  desatualizados. A reconexão é automática.
                </p>
              </div>
            </div>
          )}
          {storageError && (
            <div className="banner visual-banner" role="alert">
              <CircleAlert size={20} />
              <p>{storageError}</p>
            </div>
          )}
          {notice && (
            <div
              className={`banner ${notice.kind === "error" ? "error-banner" : "success-banner"}`}
              role={notice.kind === "error" ? "alert" : "status"}
            >
              {notice.kind === "error" ? (
                <CircleAlert size={20} />
              ) : (
                <CheckCircle2 size={20} />
              )}
              <p>{notice.message}</p>
              <button
                className="icon-button"
                aria-label="Dispensar mensagem"
                onClick={() => setNotice(null)}
              >
                <X size={17} />
              </button>
            </div>
          )}
          <div className="operation-grid">
            <section className="panel operation-panel">
              <div className="panel-heading">
                <div className="section-title">
                  <span className="step-number">01</span>
                  <div>
                    <h2>
                      {tab === "batch" || tab === "monitor"
                        ? "Arquivo e parâmetros"
                        : tab === "single"
                          ? "Dados da consulta"
                          : "Critérios da programação"}
                    </h2>
                    <p>Prepare a operação antes de iniciar.</p>
                  </div>
                </div>
              </div>
              <form onSubmit={(event) => void start(event)}>
                <fieldset disabled={locked}>
                  {(tab === "batch" || tab === "monitor") && filePicker}
                  {tab === "single" && (
                    <label className="field">
                      Número do desligamento
                      <input
                        type="text"
                        inputMode="numeric"
                        autoComplete="off"
                        required
                        value={number}
                        onChange={(e) => setNumber(e.target.value)}
                        placeholder="Informe o número completo"
                      />
                      <small>
                        O número é enviado como texto, preservando os zeros à
                        esquerda.
                      </small>
                    </label>
                  )}
                  {tab === "schedule" && (
                    <div className="form-grid">
                      <label className="field">
                        Departamento
                        <select
                          value={preferences.department}
                          onChange={(e) => update("department", e.target.value)}
                        >
                          {departments.map((d) => (
                            <option key={d}>{d}</option>
                          ))}
                        </select>
                      </label>
                      <label className="field">
                        Empresa
                        <input
                          type="text"
                          aria-describedby="company-help"
                          autoComplete="off"
                          value={company}
                          onChange={(e) => setCompany(e.target.value)}
                          placeholder="Informe o nome ou parte do nome da empresa"
                        />
                        <small id="company-help">
                          Busca na coluna Empresa Realizadora, sem diferenciar
                          maiúsculas ou acentos. Preencha empresa ou identificador;
                          se preencher ambos, os dois filtros serão aplicados.
                        </small>
                      </label>
                      <label className="field">
                        Identificador OT/ORDEM
                        <input
                          type="text"
                          required={!company.trim()}
                          aria-describedby="identifier-help"
                          autoComplete="off"
                          value={identifier}
                          onChange={(e) => setIdentifier(e.target.value)}
                          placeholder="Ex.: OT 000123 ou ORDEM: 000456"
                        />
                        <small id="identifier-help">
                          Opcional quando a empresa estiver preenchida. Aceita o
                          identificador sem prefixo e preserva zeros à esquerda.
                        </small>
                      </label>
                      <label className="field">
                        Data inicial
                        <input
                          type="date"
                          required
                          max={endDate || undefined}
                          value={startDate}
                          onChange={(e) => setStartDate(e.target.value)}
                        />
                      </label>
                      <label className="field">
                        Data final
                        <input
                          type="date"
                          required
                          min={startDate || undefined}
                          value={endDate}
                          onChange={(e) => setEndDate(e.target.value)}
                        />
                      </label>
                    </div>
                  )}
                  {tab !== "schedule" && (
                    <div className="reasons-row">{reasons}</div>
                  )}
                  {tab === "monitor" && (
                    <label className="field interval-field">
                      Intervalo entre ciclos (minutos)
                      <input
                        type="number"
                        min="1"
                        max="1440"
                        step="1"
                        required
                        value={preferences.interval_minutes}
                        onChange={(e) => {
                          const n = e.target.valueAsNumber;
                          if (Number.isInteger(n) && n >= 1 && n <= 1440)
                            update("interval_minutes", n);
                        }}
                      />
                      <small>
                        O aplicativo executará novas consultas até o
                        cancelamento.
                      </small>
                    </label>
                  )}
                </fieldset>
                <div className="form-actions">
                  <span className="execution-hint">
                    <ShieldCheck size={15} />
                    Execução local e controlada
                  </span>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={
                      !available ||
                      locked ||
                      ((tab === "batch" || tab === "monitor") && !state.input)
                    }
                  >
                    {pending === "start" || awaitingStart ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Play size={16} fill="currentColor" />
                    )}
                    {pending === "start" || awaitingStart
                      ? "Iniciando…"
                      : tab === "single"
                        ? "Consultar agora"
                        : tab === "schedule"
                          ? "Localizar programação"
                          : tab === "monitor"
                            ? "Iniciar monitoramento"
                            : "Iniciar extração"}
                    <ArrowRight size={16} />
                  </button>
                </div>
              </form>
            </section>
            <aside className="run-card" aria-labelledby="run-title">
              <div className="run-card-heading">
                <span className="eyebrow">ACOMPANHAMENTO</span>
                <Activity size={19} />
              </div>
              <h2 id="run-title">{statusLabels[state.status]}</h2>
              <p id="phase-description" aria-live="polite">
                {!bridge
                  ? "Aguardando conexão com o aplicativo desktop."
                  : phaseLabels[state.phase] ||
                    "Acompanhando o estado da operação."}
              </p>
              <div className="progress-label">
                <span>{progressLabel}</span>
                <strong>
                  {indeterminate ? "Em andamento" : `${progress}%`}
                </strong>
              </div>
              <progress
                value={indeterminate ? undefined : progress}
                max={100}
                aria-label={progressLabel}
                aria-describedby="phase-description"
              />
              <div className="run-details">
                <span>
                  {indeterminate
                    ? "Sem estimativa percentual"
                    : `${state.completed.toLocaleString("pt-BR")} de ${state.total.toLocaleString("pt-BR")}`}
                </span>
                <span>
                  {state.operation
                    ? tabs.find((item) => item.id === state.operation)?.label ||
                      state.operation
                    : "Nenhuma operação"}
                </span>
              </div>
              {state.operation === "monitor" && (
                <div className="next-run">
                  <Clock3 size={16} />
                  <div>
                    Ciclo {state.cycle}
                    <small>
                      Próxima execução:{" "}
                      {state.next_run
                        ? dateTime(state.next_run)
                        : "Não agendada"}
                    </small>
                  </div>
                </div>
              )}
              <button
                className="button cancel-button"
                disabled={
                  !bridge || (!active && !awaitingStart) || pending !== null
                }
                onClick={() => void cancel()}
              >
                <Square size={14} />
                {pending === "cancel" ? "Solicitando…" : "Cancelar operação"}
              </button>
              <span
                className="sync-time"
                data-testid="results-updated-at"
                title="Horário local da última atualização dos resultados. A verificação de conexão não altera este horário."
              >
                {state.results_updated_at
                  ? `Dados atualizados em ${dateTime(state.results_updated_at)}`
                  : "Nenhuma atualização de resultados"}
              </span>
            </aside>
          </div>
          <div className="metrics">
            <div className="metric">
              <span className="metric-icon">
                <FileSpreadsheet size={20} />
              </span>
              <div>
                <span>Registros na entrada</span>
                <strong>
                  {state.input
                    ? state.input.count.toLocaleString("pt-BR")
                    : "-"}
                </strong>
              </div>
              <small>Arquivo selecionado</small>
            </div>
            <div className="metric">
              <span className="metric-icon amber">
                <Activity size={20} />
              </span>
              <div>
                <span>Itens processados</span>
                <strong>{state.completed.toLocaleString("pt-BR")}</strong>
              </div>
              <small>Operação atual</small>
            </div>
            <div className="metric">
              <span className="metric-icon green">
                <CheckCircle2 size={20} />
              </span>
              <div>
                <span>Resultados recebidos</span>
                <strong>{state.rows.length.toLocaleString("pt-BR")}</strong>
              </div>
              <small>Disponíveis na tabela</small>
            </div>
          </div>
          {state.error && (
            <div className="banner error-banner" role="alert">
              <CircleAlert size={20} />
              <p>{state.error}</p>
            </div>
          )}
          <Results
            rows={state.rows}
            operation={state.operation}
            canExport={canExport}
            exporting={pending === "export"}
            onExport={exportResults}
          />
          {state.autosave_path?.trim() && (
            <section
              className="autosave-note"
              aria-label="Cópia automática"
              aria-live="polite"
            >
              <FileSpreadsheet size={18} />
              <div>
                <strong>Cópia automática</strong>
                <code>{state.autosave_path}</code>
              </div>
            </section>
          )}
          <section className="panel logs-panel">
            <button
              className="logs-toggle"
              aria-expanded={logsOpen}
              aria-controls="logs-content"
              onClick={() => setLogsOpen(!logsOpen)}
            >
              <Terminal size={18} />
              <strong>Registro de atividade</strong>
              <span className="count">{state.logs.length}</span>
              <span className="logs-caption">
                Detalhes técnicos da execução
              </span>
              <ChevronDown className={logsOpen ? "rotated" : ""} size={18} />
            </button>
            <div id="logs-content" hidden={!logsOpen}>
              <div
                className="log-list"
                tabIndex={0}
                aria-label="Mensagens de atividade"
              >
                {state.logs.length ? (
                  state.logs.map((log, i) => (
                    <div className="log-line" key={i}>
                      <time>{dateTime(log.time)}</time>
                      <span>{log.message}</span>
                    </div>
                  ))
                ) : (
                  <p className="log-empty">
                    Nenhuma atividade registrada. Os eventos do aplicativo
                    aparecerão aqui.
                  </p>
                )}
              </div>
            </div>
          </section>
          <footer className="page-footer">
            <span>Extrator SGD</span>
            <span>
              <ShieldCheck size={13} />
              Informação direto da origem. Sem dados simulados.
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
