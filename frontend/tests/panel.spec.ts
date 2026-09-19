import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

async function mockBridge(page: Page, late = false) {
  await page.addInitScript(
    ({ late }) => {
      const state = {
        status: "idle",
        operation: "",
        phase: "",
        completed: 0,
        total: 0,
        rows: [] as Record<string, unknown>[],
        logs: [] as { time: string; message: string }[],
        error: null,
        input: null as null | { path: string; name: string; count: number },
        next_run: null,
        results_updated_at: null as string | null,
        cycle: 0,
      };
      const harness = {
        state,
        options: null as unknown,
        inFlight: 0,
        maxInFlight: 0,
        pollCount: 0,
        failStart: false,
        failPoll: false,
      };
      const api = {
        async get_state() {
          harness.pollCount++;
          harness.inFlight++;
          harness.maxInFlight = Math.max(harness.maxInFlight, harness.inFlight);
          try {
            await new Promise((resolve) => setTimeout(resolve, 180));
            if (harness.failPoll) throw new Error("Falha de conexão de teste");
            return JSON.parse(JSON.stringify(state));
          } finally {
            harness.inFlight--;
          }
        },
        async select_input() {
          state.input = {
            path: "C:\\test\\entrada.csv",
            name: "entrada.csv",
            count: 23,
          };
          return { ok: true, input: state.input };
        },
        async start_job(options: { operation: string }) {
          if (harness.failStart) throw new Error("Falha de início de teste");
          harness.options = options;
          state.status = "running";
          state.operation = options.operation;
          state.phase =
            options.operation === "schedule" ? "schedule" : "status";
          state.total = 23;
          state.results_updated_at = "2026-09-08T15:00:00+00:00";
          state.rows = Array.from({ length: 23 }, (_, i) =>
            options.operation === "schedule"
              ? {
                  codigo_programacao: `P${i}`,
                  Estado: i % 2 ? "Negado" : "Executado",
                  equipe: "Equipe de teste",
                  campo_extra: "Valor de teste",
                }
              : {
                  numero_desligamento: String(i).padStart(6, "0"),
                  status: i % 2 ? "Status B" : "Status A",
                  departamento: "Departamento Exemplo",
                  data: "2026-09-08",
                  motivo_negacao: "",
                  consultado_em: "2026-09-08T12:00:00",
                },
          );
          state.logs = [
            {
              time: "2026-09-08T12:00:00",
              message: "Evento exclusivo do teste automatizado",
            },
          ];
          return { ok: true };
        },
        async cancel_job() {
          state.status = "cancelled";
          state.phase = "cancelled";
          return { ok: true };
        },
        async export_results() {
          return { ok: true, path: "C:\\test\\resultado.xlsx" };
        },
      };
      Object.assign(window, { harness });
      const connect = () => {
        Object.assign(window, { pywebview: { api } });
        window.dispatchEvent(new Event("pywebviewready"));
      };
      if (late) Object.assign(window, { connect });
      else connect();
    },
    { late },
  );
}

test("modo visual, navegação móvel e preferências robustas", async ({
  page,
}) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("invalid-preference-seeded")) return;
    localStorage.setItem("sgd.preferences.v1", "{invalid");
    sessionStorage.setItem("invalid-preference-seeded", "true");
  });
  await page.goto("/");
  await expect(
    page.getByText("Modo visual · aplicativo desktop não conectado"),
  ).toBeVisible();
  await expect(page.locator(".topbar")).toHaveCount(0);
  await expect(page.getByText("CONTROLE E VISIBILIDADE")).toHaveCount(0);
  await expect(
    page.getByText(
      "Do arquivo à informação. Consulte seus desligamentos em uma única execução.",
    ),
  ).toHaveCount(0);
  await expect(page.getByText("Necessario VPN")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Ativar tema escuro" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() =>
      page.evaluate(
        () => JSON.parse(localStorage.getItem("sgd.preferences.v1")!).theme,
      ),
    )
    .toBe("dark");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(14, 21, 28)",
  );
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: "Ativar tema claro" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.locator(".brand").getByText("Extrator SGD", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("SGD / OPS")).toHaveCount(0);
  await expect(page.getByText("CENTRAL DE OPERAÇÕES")).toHaveCount(0);
  await expect(
    page.getByText(
      "Qualquer operação a ser executada pelo aplicativo é efetuado apenas mediante conexão VPN para acesso a base",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Escolher arquivo" }),
  ).toBeDisabled();
  await expect(
    page.getByText("Estrutura obrigatória do arquivo"),
  ).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: "numero_desligamento" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Iniciar extração" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Exportar Excel" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Configurações", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Tempo limite de status/programação (segundos)"),
  ).toHaveCount(0);
  await expect(page.getByLabel("Tentativas por consulta")).toHaveCount(0);
  await expect(page.getByText("Diagnóstico detalhado")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Abrir navegação" }).click();
  await page
    .getByRole("button", { name: "Consulta rápida", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Consulta rápida", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Número do desligamento").fill("000123");
  await expect(
    page.getByRole("button", { name: "Consultar agora" }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("bridge tardio, lote, tabela, modal, cancelamento e exportação", async ({
  page,
}) => {
  await mockBridge(page, true);
  await page.goto("/");
  await expect(
    page.getByText("Modo visual · aplicativo desktop não conectado"),
  ).toBeVisible();
  await page.evaluate(() =>
    (window as unknown as { connect: () => void }).connect(),
  );
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  await page.getByRole("button", { name: "Escolher arquivo" }).click();
  await expect(page.getByText("23 registros identificados")).toBeVisible();
  await page.getByRole("button", { name: "Iniciar extração" }).click();
  await expect(
    page.getByRole("heading", { name: "Em execução" }),
  ).toBeVisible();
  await expect(page.getByText("1–10 de 23 registros")).toBeVisible();
  await page.getByRole("button", { name: "Próxima página" }).click();
  await expect(page.getByText("11–20 de 23 registros")).toBeVisible();
  await page.getByLabel("Pesquisar em todos os campos").fill("000002");
  await expect(
    page.getByText("1–1 de 1 registros", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Ver detalhes do registro 000002" })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("Pesquisar em todos os campos").fill("");
  await page.getByLabel("Filtrar por status").selectOption("Status B");
  await expect(
    page.getByText("1–10 de 11 registros", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Nº do desligamento" }).click();
  await expect(
    page.getByRole("columnheader", { name: "Nº do desligamento" }),
  ).toHaveAttribute("aria-sort", "ascending");
  await page.getByRole("button", { name: "Cancelar operação" }).click();
  await expect(
    page.getByRole("heading", { name: "Cancelado", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Exportar Excel" }).click();
  await expect(
    page.getByText("Excel exportado para C:\\test\\resultado.xlsx"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Registro de atividade" }).click();
  await expect(
    page.getByText("Evento exclusivo do teste automatizado"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { harness: { maxInFlight: number } }).harness
          .maxInFlight,
    ),
  ).toBe(1);
});

test("destaca os status operacionais com cores específicas", async ({
  page,
}) => {
  await mockBridge(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Escolher arquivo" }).click();
  await page.getByRole("button", { name: "Iniciar extração" }).click();
  const statuses = [
    ["Negado", "status-negado"],
    ["Cancelado", "status-cancelado"],
    ["Eliminado", "status-eliminado"],
    ["Não Solicitado", "status-nao-solicitado"],
    ["Sem Encerrar", "status-sem-encerrar"],
    ["Solicitado", "status-solicitado"],
    ["Validado", "status-validado"],
    ["Autorizado", "status-autorizado"],
    ["Aprovado", "status-aprovado"],
    ["Confirmado", "status-confirmado"],
    ["Executado", "status-executado"],
  ];
  await page.evaluate((values) => {
    const harness = (
      window as unknown as {
        harness: { state: { rows: Record<string, unknown>[] } };
      }
    ).harness;
    values.forEach(([value], index) => {
      harness.state.rows[index].status = value;
    });
  }, statuses);
  await page.getByLabel("Por página").selectOption("25");
  for (const [value, className] of statuses) {
    const badge = page
      .locator(".status-tag")
      .filter({ hasText: new RegExp(`^${value}$`) });
    await expect(badge).toHaveClass(new RegExp(`\\b${className}\\b`));
  }
});

for (const statusKey of ["status", "Estado"]) {
  test(`cores e filtro reconhecem a coluna ${statusKey}`, async ({ page }) => {
    await mockBridge(page);
    await page.goto("/");
    await expect(page.getByTestId("connection-status")).toHaveText("Desktop conectado");
    await page.evaluate((key) => {
      const harness = (window as unknown as {
        harness: { state: Record<string, unknown> };
      }).harness;
      Object.assign(harness.state, {
        status: "completed", phase: "completed",
        operation: key === "Estado" ? "schedule" : "batch",
        rows: ["Executado", "Negado", "Eliminado", "Negado"].map((status, i) => ({
          [key === "Estado" ? "Referência" : "numero_desligamento"]: String(i + 1),
          [key]: status,
          "Empresa Realizadora": i === 3 ? "Beta" : "Alfa",
        })),
      });
    }, statusKey);
    const table = page.locator(".results tbody");
    await expect(table.locator("tr")).toHaveCount(4);
    for (const theme of ["claro", "escuro"]) {
      if (theme === "escuro") await page.getByRole("button", { name: "Ativar tema escuro" }).click();
      await expect(table.locator(".status-executado")).toHaveText("Executado");
      await expect(table.locator(".status-negado")).toHaveCount(2);
      await expect(table.locator(".status-eliminado")).toHaveText("Eliminado");
    }
    const filter = page.getByLabel("Filtrar por status");
    await expect(filter.locator("option")).toHaveText([
      "Todos os status", "Eliminado", "Executado", "Negado",
    ]);
    await filter.selectOption("Negado");
    await expect(table.locator("tr")).toHaveCount(2);
    await expect(table.locator(".status-negado")).toHaveCount(2);
    await page.getByLabel("Pesquisar em todos os campos").fill("Alfa");
    await expect(table.locator("tr")).toHaveCount(1);
    await table.getByRole("button", { name: /Ver detalhes/ }).click();
    await expect(page.getByRole("dialog").locator(".status-negado")).toHaveText("Negado");
    await page.keyboard.press("Escape");
    await page.getByLabel("Pesquisar em todos os campos").fill("Inexistente");
    await expect(page.getByText("Nenhum registro encontrado")).toBeVisible();
    await page.getByRole("button", { name: "Limpar filtros" }).click();
    await expect(table.locator("tr")).toHaveCount(4);
  });
}

for (const zone of [
  { id: "America/Sao_Paulo", expected: "14/09/2026, 13:28:50" },
  { id: "America/Manaus", expected: "14/09/2026, 12:28:50" },
]) {
  test.describe(`horário local em ${zone.id}`, () => {
    test.use({ timezoneId: zone.id });
    test("converte UTC na tabela e detalhes e ordena pelo instante real", async ({ page }) => {
      await mockBridge(page);
      await page.goto("/");
      await expect(page.getByTestId("connection-status")).toHaveText("Desktop conectado");
      await page.evaluate(() => {
        const harness = (window as unknown as {
          harness: { state: Record<string, unknown> };
        }).harness;
        Object.assign(harness.state, {
          operation: "single", status: "completed", phase: "completed",
          results_updated_at: "2026-09-14T16:28:50.071124+00:00",
          rows: [
            { numero_desligamento: "2", status: "Executado", consultado_em: "2026-09-14T13:29:00-03:00" },
            { numero_desligamento: "1", status: "Negado", consultado_em: "2026-09-14T16:28:50.071124+00:00" },
          ],
        });
      });
      const table = page.locator(".results tbody");
      await expect(table.getByText(zone.expected, { exact: true })).toBeVisible();
      await expect(page.getByTestId("results-updated-at")).toHaveText(`Dados atualizados em ${zone.expected}`);
      await expect(table).not.toContainText("+00:00");
      await page.getByRole("button", { name: "Consultado em", exact: true }).click();
      await expect(table.locator("tr").first().locator("td").first()).toHaveText("1");
      await table.getByRole("button", { name: "Ver detalhes do registro 1", exact: true }).click();
      await expect(page.getByRole("dialog").getByText(zone.expected, { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
      await page.getByLabel("Pesquisar em todos os campos").fill(zone.expected);
      await expect(table.locator("tr")).toHaveCount(1);
      await expect(table.locator("tr").first().locator("td").first()).toHaveText("1");
    });
  });
}

test("última atualização acompanha os dados, não polling ou exportação", async ({ page }) => {
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText("Desktop conectado");
  const updated = page.getByTestId("results-updated-at");
  await expect(updated).toHaveText("Nenhuma atualização de resultados");
  await page.evaluate(() => {
    const harness = (window as unknown as { harness: { state: Record<string, unknown> } }).harness;
    Object.assign(harness.state, {
      operation: "monitor", status: "waiting", phase: "waiting", cycle: 1,
      results_updated_at: "2026-09-14T16:00:00Z",
      rows: [{ numero_desligamento: "1", status: "Executado" }],
    });
  });
  await expect(updated).toContainText("Dados atualizados em");
  const first = await updated.textContent();
  const polls = await page.evaluate(() => (
    window as unknown as { harness: { pollCount: number } }
  ).harness.pollCount);
  await expect.poll(() => page.evaluate(() => (
    window as unknown as { harness: { pollCount: number } }
  ).harness.pollCount)).toBeGreaterThan(polls + 2);
  await expect(updated).toHaveText(first!);
  await page.getByRole("button", { name: "Exportar Excel" }).click();
  await expect(updated).toHaveText(first!);
  // Os mesmos valores em outro ciclo ainda representam uma atualização.
  await page.evaluate(() => {
    const harness = (window as unknown as { harness: { state: Record<string, unknown> } }).harness;
    Object.assign(harness.state, {
      cycle: 2, results_updated_at: "2026-09-14T16:01:00Z", status: "completed", phase: "completed",
    });
  });
  await expect(updated).not.toHaveText(first!);
  const completed = await updated.textContent();
  const completedPolls = await page.evaluate(() => (
    window as unknown as { harness: { pollCount: number } }
  ).harness.pollCount);
  await expect.poll(() => page.evaluate(() => (
    window as unknown as { harness: { pollCount: number } }
  ).harness.pollCount)).toBeGreaterThan(completedPolls + 2);
  await expect(updated).toHaveText(completed!);
});

test("consulta preserva zeros e permite tentar novamente após falha", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "sgd.preferences.v1",
      JSON.stringify({
        timeout: 500,
        reason_timeout: 500,
        attempts: 9,
        delay: 30,
        debug: true,
      }),
    ),
  );
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  await page
    .getByRole("button", { name: "Consulta rápida", exact: true })
    .click();
  await page.getByLabel("Número do desligamento").fill("0000123");
  await page.evaluate(() => {
    (
      window as unknown as { harness: { failStart: boolean } }
    ).harness.failStart = true;
  });
  await page.getByRole("button", { name: "Consultar agora" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Falha de início de teste",
  );
  await expect(
    page.getByRole("button", { name: "Consultar agora" }),
  ).toBeEnabled();
  await page.evaluate(() => {
    (
      window as unknown as { harness: { failStart: boolean } }
    ).harness.failStart = false;
  });
  await page.getByRole("button", { name: "Consultar agora" }).click();
  await expect(
    page.getByRole("heading", { name: "Em execução" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { harness: { options: unknown } }).harness
          .options,
    ),
  ).toMatchObject({
    number: "0000123",
    timeout: 30,
    reason_timeout: 120,
    attempts: 3,
    delay: 1,
    debug: false,
    include_reasons: true,
  });
});

test("programação usa colunas dinâmicas e recupera polling após erro", async ({
  page,
}) => {
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  await page
    .getByRole("button", { name: "Localizar programação", exact: true })
    .first()
    .click();
  const department = page.getByRole("combobox", {
    name: "Departamento",
    exact: true,
  });
  const availableDepartment = await department
    .locator("option")
    .last()
    .innerText();
  await department.selectOption({ label: availableDepartment });
  await page.getByLabel("Identificador OT/ORDEM").fill("0007");
  await page.getByLabel("Data inicial").fill("2026-09-01");
  await page.getByLabel("Data final").fill("2026-09-08");
  await page
    .getByRole("button", { name: "Localizar programação", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("columnheader", { name: "codigo programacao" }),
  ).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: "campo extra" }),
  ).toBeVisible();
  await expect(
    page.getByRole("columnheader", { name: "Nº do desligamento" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("progressbar", { name: "Progresso da busca" }),
  ).not.toHaveAttribute("value");
  await expect(
    page.getByText(
      "Localizando programações pelos filtros informados no período selecionado. Aguarde o retorno da consulta.",
    ),
  ).toBeVisible();
  await page.evaluate(() => {
    (window as unknown as { harness: { failPoll: boolean } }).harness.failPoll =
      true;
  });
  await expect(
    page.getByText("Não foi possível atualizar o estado"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancelar operação" }),
  ).toBeEnabled();
  await page.evaluate(() => {
    (window as unknown as { harness: { failPoll: boolean } }).harness.failPoll =
      false;
  });
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
});

test("monitoramento envia intervalo e acompanha espera entre ciclos", async ({
  page,
}, testInfo) => {
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  await page
    .getByRole("button", { name: "Monitoramento", exact: true })
    .click();
  await page.getByRole("button", { name: "Escolher arquivo" }).click();
  await page.getByLabel("Intervalo entre ciclos (minutos)").fill("5");
  await page.getByRole("button", { name: "Iniciar monitoramento" }).click();
  await expect(
    page.getByRole("heading", { name: "Em execução" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Exportar Excel" }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () =>
        (
          window as unknown as {
            harness: {
              options: { operation: string; interval_minutes: number };
            };
          }
        ).harness.options,
    ),
  ).toMatchObject({
    operation: "monitor",
    interval_minutes: 5,
    timeout: 30,
    reason_timeout: 120,
    include_reasons: true,
  });
  await page.evaluate(() => {
    const harness = (
      window as unknown as {
        harness: {
          state: {
            status: string;
            phase: string;
            cycle: number;
            next_run: string;
          };
        };
      }
    ).harness;
    harness.state.status = "waiting";
    harness.state.phase = "waiting";
    harness.state.cycle = 2;
    harness.state.next_run = "2026-09-08T12:05:00";
  });
  await expect(
    page.getByRole("heading", { name: "Aguardando próximo ciclo" }),
  ).toBeVisible();
  await expect(page.getByText("Ciclo 2", { exact: false })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Iniciar monitoramento" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Trocar arquivo" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Exportar Excel" }).click();
  await expect(
    page.getByText("Excel exportado para C:\\test\\resultado.xlsx"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Aguardando próximo ciclo" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancelar operação" }),
  ).toBeEnabled();
  await page.screenshot({
    path: testInfo.outputPath("desktop.png"),
    animations: "disabled",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("mobile.png"),
    animations: "disabled",
    fullPage: true,
  });
});

test("programação rejeita identificador vazio, prefixo isolado e caracteres de controle", async ({
  page,
}) => {
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  await page
    .getByRole("button", { name: "Localizar programação", exact: true })
    .first()
    .click();
  await page.getByLabel("Data inicial").fill("2026-09-01");
  await page.getByLabel("Data final").fill("2026-09-08");
  const identifier = page.getByLabel("Identificador OT/ORDEM");
  const submit = page
    .getByRole("button", { name: "Localizar programação", exact: true })
    .last();
  await expect(identifier).toHaveAttribute("required", "");
  await expect(identifier).toHaveAttribute(
    "placeholder",
    "Ex.: OT 000123 ou ORDEM: 000456",
  );
  await submit.click();
  expect(
    await identifier.evaluate(
      (input: HTMLInputElement) => input.validity.valueMissing,
    ),
  ).toBe(true);
  for (const value of [
    "   ",
    "OT",
    "ordem: ",
    " OT # ",
    "ORDEM -",
    "000\u0001123",
  ]) {
    await identifier.fill(value);
    await submit.click();
    await expect(page.getByRole("alert")).toContainText(
      value.includes("\u0001")
        ? "A OT ou ORDEM contém caracteres inválidos."
        : value.trim()
          ? "Informe uma OT ou ORDEM para localizar."
          : "Informe uma OT/ORDEM ou uma empresa para localizar.",
    );
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { harness: { options: unknown } }).harness
            .options,
      ),
    ).toBeNull();
  }
});

for (const identifier of ["", "OT:000123"]) {
  test(`programação busca empresa com identificador ${identifier || "vazio"}`, async ({
    page,
  }) => {
    await mockBridge(page);
    await page.goto("/");
    await expect(page.getByTestId("connection-status")).toHaveText(
      "Desktop conectado",
    );
    await page
      .getByRole("button", { name: "Localizar programação", exact: true })
      .first()
      .click();
    const company = page.getByRole("textbox", { name: /^Empresa/ });
    const order = page.getByLabel("Identificador OT/ORDEM");
    await company.fill("  Empresa Ágata  ");
    await expect(order).not.toHaveAttribute("required");
    await order.fill(identifier);
    await page.getByLabel("Data inicial").fill("2026-09-01");
    await page.getByLabel("Data final").fill("2026-09-08");
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("button", { name: "Localizar programação", exact: true })
      .last()
      .click();
    await expect(page.getByRole("heading", { name: "Em execução" })).toBeVisible();
    await expect(company).toBeDisabled();
    expect(
      await page.evaluate(
        () => (window as unknown as { harness: { options: unknown } }).harness.options,
      ),
    ).toMatchObject({
      operation: "schedule",
      company: "Empresa Ágata",
      identifier,
      start_date: "2026-09-01",
      end_date: "2026-09-08",
    });
  });
}

test("programação exige um filtro e rejeita empresa inválida", async ({ page }) => {
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  await page
    .getByRole("button", { name: "Localizar programação", exact: true })
    .first()
    .click();
  const company = page.getByRole("textbox", { name: /^Empresa/ });
  const order = page.getByLabel("Identificador OT/ORDEM");
  const submit = page
    .getByRole("button", { name: "Localizar programação", exact: true })
    .last();
  await company.fill("Empresa Ágata");
  await expect(order).not.toHaveAttribute("required");
  await submit.click();
  expect(
    await page.getByLabel("Data inicial").evaluate(
      (input: HTMLInputElement) => input.validity.valueMissing,
    ),
  ).toBe(true);
  await company.fill("   ");
  await expect(order).toHaveAttribute("required", "");
  await page.getByLabel("Data inicial").fill("2026-09-01");
  await page.getByLabel("Data final").fill("2026-09-08");
  for (const value of ["...", "Empresa\u0001Ágata"]) {
    await company.fill(value);
    await submit.click();
    await expect(page.getByRole("alert")).toContainText(
      "A empresa contém caracteres inválidos.",
    );
  }
  await company.fill("Empresa Ágata");
  await order.fill("OT:");
  await submit.click();
  await expect(page.getByRole("alert")).toContainText(
    "Informe uma OT ou ORDEM para localizar.",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { harness: { options: unknown } }).harness.options,
    ),
  ).toBeNull();
});

for (const identifier of [
  "000123",
  "OT 000123",
  " ordem: 000456 ",
  "OT#000789",
  "ORDEM-001234",
]) {
  test(`programação aceita e preserva identificador ${identifier.trim()}`, async ({
    page,
  }) => {
    await mockBridge(page);
    await page.goto("/");
    await expect(page.getByTestId("connection-status")).toHaveText(
      "Desktop conectado",
    );
    await page
      .getByRole("button", { name: "Localizar programação", exact: true })
      .first()
      .click();
    await page.getByLabel("Identificador OT/ORDEM").fill(identifier);
    await page.getByLabel("Data inicial").fill("2026-09-01");
    await page.getByLabel("Data final").fill("2026-09-08");
    await page
      .getByRole("button", { name: "Localizar programação", exact: true })
      .last()
      .click();
    await expect(
      page.getByRole("heading", { name: "Em execução" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          (
            window as unknown as {
              harness: { options: { identifier: string } };
            }
          ).harness.options.identifier,
      ),
    ).toBe(identifier.trim());
  });
}

test("fases têm tradução e motivos não exibem 100% dos status como conclusão", async ({
  page,
}) => {
  await mockBridge(page);
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveText(
    "Desktop conectado",
  );
  const phases = {
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
  for (const [phase, label] of Object.entries(phases)) {
    await page.evaluate((phase) => {
      const state = (
        window as unknown as {
          harness: {
            state: {
              phase: string;
              status: string;
              completed: number;
              total: number;
            };
          };
        }
      ).harness.state;
      Object.assign(state, {
        phase,
        status: ["starting", "status", "reasons", "schedule"].includes(phase)
          ? "running"
          : phase,
        completed: 23,
        total: 23,
      });
    }, phase);
    await expect(page.getByText(label, { exact: true })).toBeVisible();
    const progress = page.getByRole("progressbar");
    if (phase === "reasons" || phase === "schedule") {
      await expect(progress).not.toHaveAttribute("value");
      await expect(page.getByText("100%", { exact: true })).toHaveCount(0);
      await expect(page.getByText("Sem estimativa percentual")).toBeVisible();
    } else {
      await expect(progress).toHaveAttribute("value", "100");
    }
    if (phase === "status")
      await expect(progress).toHaveAccessibleName("Progresso dos status");
  }
});
