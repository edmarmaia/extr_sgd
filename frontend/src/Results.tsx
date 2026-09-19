import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  Search,
  Table2,
  X,
} from "lucide-react";
import { dateTime, text } from "./api";
import type { Row } from "./api";

const labels: Record<string, string> = {
  numero_desligamento: "Nº do desligamento",
  status: "Status",
  departamento: "Departamento",
  data: "Data",
  motivo_negacao: "Motivo da negação",
  consultado_em: "Consultado em",
};
const label = (key: string) => labels[key] || key.replace(/_/g, " ");
const standardKeys = Object.keys(labels);
const isStatusKey = (key: string) => ["status", "estado"].includes(key.trim().toLowerCase());
const rowStatus = (row: Row) => text(
  Object.entries(row).find(([key, value]) => isStatusKey(key) && text(value).trim())?.[1],
).trim();
const displayValue = (key: string, value: unknown) =>
  key === "consultado_em" ? dateTime(text(value) || null) : text(value);

function compareValues(key: string, a: unknown, b: unknown) {
  if (key === "consultado_em") {
    const first = Date.parse(text(a));
    const second = Date.parse(text(b));
    if (Number.isFinite(first) && Number.isFinite(second)) return first - second;
  }
  return text(a).localeCompare(text(b), "pt-BR", { numeric: true });
}

const statusTones: Record<string, string> = {
  NEGADO: "negado",
  DENEGADO: "negado",
  CANCELADO: "cancelado",
  ELIMINADO: "eliminado",
  "NAO SOLICITADO": "nao-solicitado",
  "NO SOLICITADO": "nao-solicitado",
  "SEM ENCERRAR": "sem-encerrar",
  "SIN CUMPLIMENTAR": "sem-encerrar",
  SOLICITADO: "solicitado",
  VALIDADO: "validado",
  AUTORIZADO: "autorizado",
  APROVADO: "aprovado",
  CONFIRMADO: "confirmado",
  EXECUTADO: "executado",
};

function statusTone(value: unknown) {
  const normalized = text(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toUpperCase();
  return statusTones[normalized] || "neutral";
}

function Detail({ row, close }: { row: Row; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="detail-modal"
      aria-labelledby="detail-title"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-heading">
        <div>
          <span className="eyebrow">INSPEÇÃO DO REGISTRO</span>
          <h2 id="detail-title">Detalhes do resultado</h2>
        </div>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Fechar detalhes"
          autoFocus
        >
          <X size={20} />
        </button>
      </div>
      <dl className="detail-list">
        {Object.entries(row).map(([key, value]) => (
          <div key={key}>
            <dt>{label(key)}</dt>
            <dd>
              {isStatusKey(key) && text(value) ? (
                <span className={`status-tag status-${statusTone(value)}`}>
                  {text(value)}
                </span>
              ) : displayValue(key, value) || "Não informado"}
            </dd>
          </div>
        ))}
      </dl>
      <div className="modal-footer">
        <button className="button secondary" onClick={close}>
          Fechar detalhes
        </button>
      </div>
    </dialog>
  );
}

export default function Results({
  rows,
  operation,
  canExport,
  exporting,
  onExport,
}: {
  rows: Row[];
  operation: string;
  canExport: boolean;
  exporting: boolean;
  onExport: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<{ key: string; direction: 1 | -1 } | null>(
    null,
  );
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [detail, setDetail] = useState<Row | null>(null);
  const dynamicKeys = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const keys =
    operation === "schedule"
      ? dynamicKeys
      : [
          ...standardKeys,
          ...dynamicKeys.filter((key) => !standardKeys.includes(key)),
        ];
  const statuses = [
    ...new Set(rows.map(rowStatus).filter(Boolean)),
  ].sort();
  const filtered = rows.filter(
    (row) =>
      (!status || rowStatus(row) === status) &&
      Object.entries(row).some(([key, value]) =>
        `${text(value)} ${displayValue(key, value)}`
          .toLocaleLowerCase("pt-BR")
          .includes(query.toLocaleLowerCase("pt-BR")),
      ),
  );
  if (sort)
    filtered.sort(
      (a, b) =>
        compareValues(sort.key, a[sort.key], b[sort.key]) * sort.direction,
    );
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const start = (currentPage - 1) * pageSize;
  useEffect(() => {
    setPage(1);
    setStatus("");
    setSort(null);
    setQuery("");
  }, [operation]);
  return (
    <section className="panel results" aria-labelledby="results-title">
      <div className="panel-heading">
        <div>
          <div className="title-line">
            <h2 id="results-title">Resultados</h2>
            <span className="count">{rows.length}</span>
          </div>
          <p>Registros retornados pela operação mais recente.</p>
        </div>
        <button
          className="button secondary"
          onClick={() => void onExport()}
          disabled={!canExport || exporting}
          title="Exporta uma cópia dos resultados disponíveis, não apenas o filtro. Durante a espera do monitoramento, não interrompe os próximos ciclos."
        >
          <Download size={16} />
          {exporting ? "Exportando…" : "Exportar Excel"}
        </button>
      </div>
      <div className="table-toolbar">
        <label className="search-field">
          <Search size={17} />
          <input
            aria-label="Pesquisar em todos os campos"
            placeholder="Pesquisar nos resultados…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
          />
          <span className="search-hint">Todos os campos</span>
        </label>
        <label className="status-filter">
          <span className="sr-only">Filtrar por status</span>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Todos os status</option>
            {statuses.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      {rows.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">
            <Table2 size={27} />
          </span>
          <h3>Seu próximo resultado começa aqui</h3>
          <p>
            Configure uma operação e inicie a execução.
            <br />
            Os registros aparecerão nesta área, sem dados de demonstração.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <Search size={28} />
          <h3>Nenhum registro encontrado</h3>
          <p>Experimente outro termo ou remova o filtro de status.</p>
          <button
            className="button secondary"
            onClick={() => {
              setQuery("");
              setStatus("");
              setPage(1);
            }}
          >
            Limpar filtros
          </button>
        </div>
      ) : (
        <div
          className="table-scroll"
          role="region"
          aria-label="Tabela de resultados, role horizontalmente para ver mais colunas"
          tabIndex={0}
        >
          <table>
            <caption className="sr-only">
              Resultados da operação. Use os cabeçalhos para ordenar.
            </caption>
            <thead>
              <tr>
                {keys.map((key) => (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={
                      sort?.key === key
                        ? sort.direction === 1
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      onClick={() =>
                        setSort({
                          key,
                          direction:
                            sort?.key === key && sort.direction === 1 ? -1 : 1,
                        })
                      }
                    >
                      {label(key)}
                      {sort?.key === key ? (
                        sort.direction === 1 ? (
                          <ArrowUp size={13} />
                        ) : (
                          <ArrowDown size={13} />
                        )
                      ) : (
                        <ArrowUpDown size={13} />
                      )}
                    </button>
                  </th>
                ))}
                <th scope="col">Detalhes</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(start, start + pageSize).map((row, index) => (
                <tr key={start + index}>
                  {keys.map((key) => (
                    <td key={key}>
                      {isStatusKey(key) && text(row[key]) ? (
                        <span
                          className={`status-tag status-${statusTone(row[key])}`}
                        >
                          {text(row[key])}
                        </span>
                      ) : (
                        <span
                          className={
                            key === "numero_desligamento"
                              ? "record-number"
                              : "cell-text"
                          }
                          title={key === "consultado_em"
                            ? `${displayValue(key, row[key])} (horário local)`
                            : text(row[key])}
                        >
                          {displayValue(key, row[key]) || "Não informado"}
                        </span>
                      )}
                    </td>
                  ))}
                  <td>
                    <button
                      className="icon-button"
                      onClick={() => setDetail(row)}
                      aria-label={`Ver detalhes do registro ${text(row.numero_desligamento) || start + index + 1}`}
                    >
                      <Eye size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-footer">
        <span>
          {filtered.length
            ? `${start + 1}–${Math.min(start + pageSize, filtered.length)} de ${filtered.length} registros`
            : "0 registros"}
          {query || status ? ` · ${rows.length} no total` : ""}
        </span>
        <div className="pagination">
          <label>
            Por página{" "}
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <button
            className="icon-button"
            aria-label="Página anterior"
            disabled={currentPage <= 1}
            onClick={() => setPage(currentPage - 1)}
          >
            <ChevronLeft size={17} />
          </button>
          <span>
            {currentPage} / {pages}
          </span>
          <button
            className="icon-button"
            aria-label="Próxima página"
            disabled={currentPage >= pages}
            onClick={() => setPage(currentPage + 1)}
          >
            <ChevronRight size={17} />
          </button>
        </div>
      </div>
      {detail && <Detail row={detail} close={() => setDetail(null)} />}
    </section>
  );
}
