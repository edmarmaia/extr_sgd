# Extrator SGD

Aplicativo desktop Windows com React + TypeScript e Python, hospedado em pywebview / Microsoft Edge WebView2. A interface usa recursos locais, sem CDN, sem Node.js na maquina do usuario final e sem servidor de API separado. O pywebview serve os recursos locais da interface em loopback.

Antes de executar ou compilar, copie `config.example.json` para `config.local.json` e preencha a configuracao do seu ambiente.

## Executar a interface

Requisitos: Windows, Python 3.10 ou superior, Microsoft Edge WebView2 Runtime e acesso a rede corporativa dos sistemas consultados. Node.js 22 LTS e npm sao necessarios apenas para desenvolver ou compilar o frontend.

Na raiz do projeto:

```powershell
Copy-Item config.example.json config.local.json
# Edite config.local.json com os valores do ambiente.
python -m pip install -r requirements.txt
```

Na pasta `frontend`:

```powershell
npm ci
npm run build
```

Na raiz:

```powershell
python desktop.py
```

## Funcionalidades

- Extracao em lote de CSV, XLS e XLSX com a coluna obrigatoria `numero_desligamento`.
- Consulta rapida de um SGD, departamento, data e motivo de negacao opcional.
- Busca de programacao por departamento, periodo e identificador OT/ORDEM e/ou empresa realizadora.
- Monitoramento com consulta imediata, intervalo configuravel e cancelamento.
- Motivos de negacao opcionais, inclusive no monitoramento.
- Tabela pesquisavel, ordenavel, paginada e com detalhes de cada registro.
- Exportacao Excel para destino escolhido, com confirmacao de substituicao.
- Configuracoes persistentes de timeout, tentativas, pausas e diagnostico.
- Progresso por etapa, logs e preservacao de resultados parciais.

Ha uma operacao de consulta por vez. Cancelar impede novas consultas, mas uma requisicao HTTP em andamento pode precisar terminar ou atingir o timeout. Ao fechar durante uma operacao, o aplicativo oferece cancelamento e permanece aberto para terminar a gravacao; feche novamente quando ele concluir.

### Localizar programacao por empresa (versao 1.2.0)

Informe departamento, data inicial e data final, e preencha **Empresa** e/ou
**Identificador OT/ORDEM**. Com Empresa preenchida, o identificador e opcional.
A busca retorna todas as linhas correspondentes da coluna **Empresa Realizadora**
no relatorio baixado para o departamento e periodo selecionados. Aceita parte do
nome e ignora maiusculas, acentos e variacoes de espacos; por exemplo, `empresa alfa`
encontra `Empresa Alfa Servicos`. Se ambos os filtros forem preenchidos,
somente linhas que correspondem aos dois sao retornadas. Pelo menos um filtro
deve estar preenchido. Os resultados continuam disponiveis para exportacao Excel.

### Status e horarios dos resultados (versao 1.2.1)

A coluna `Estado` da programacao usa as mesmas cores e o mesmo filtro da coluna
`status` das outras consultas. O filtro de status pode ser combinado com a busca
textual nos resultados.

**Dados atualizados em** indica quando o backend publicou os resultados exibidos.
Esse horario permanece fixo apos a conclusao e durante a espera do monitoramento;
a verificacao periodica da ponte desktop e a exportacao nao o alteram. Um novo
snapshot atualiza o horario mesmo se os valores consultados continuarem iguais.

`Consultado em`, os logs, a proxima execucao e a ultima atualizacao sao exibidos
no fuso horario local configurado no computador. Os timestamps do backend continuam
em UTC; a tabela e os detalhes fazem a conversao para apresentacao, sem subtrair
um deslocamento fixo. Datas previstas recebidas do SGD mantem o formato original.

## Arquivos e privacidade

Lotes e monitoramento salvam automaticamente em `%LOCALAPPDATA%/ExtratorSGD/results/<execucao>/resultado.xlsx`. O caminho aparece no registro de atividade. Cada execucao tem uma pasta propria; ciclos do mesmo monitoramento atualizam seu snapshot atomicamente. Cancelamento e erro tambem tentam salvar os resultados parciais. Falhas de gravacao aparecem como avisos no registro; os dados continuam exportaveis na interface.

Diferentemente do menu antigo, o desktop nao sobrescreve `saida.xlsx` ao lado da entrada. Use **Exportar Excel** para escolher outro destino. Durante a espera entre ciclos, a exportacao permite salvar o ultimo snapshot sem parar o monitoramento. Consulta rapida e programacao precisam de exportacao explicita para manter seus resultados apos fechar.

Se um ciclo posterior do monitoramento for interrompido, o ultimo ciclo completo permanece na tabela e em `resultado.xlsx`. Os novos resultados parciais sao salvos separadamente em `resultado_parcial.xlsx`, na mesma pasta. O timeout dos relatorios de negacao tem configuracao independente, com padrao de 120 segundos; consultas de status e programacao usam 30 segundos por padrao.

Relatorios intermediarios de negacao sao temporarios. Com diagnostico habilitado, HTMLs sao preservados em `%LOCALAPPDATA%/ExtratorSGD/diagnostics/<execucao>`; o caminho aparece nos logs. Esses arquivos e os resultados podem conter dados corporativos: nao os compartilhe indiscriminadamente. Nao ha limpeza automatica das pastas de resultados/diagnostico; remova os arquivos quando nao forem mais necessarios. O perfil WebView e as preferencias ficam em `%LOCALAPPDATA%/ExtratorSGD/webview`; erros do desktop em `desktop.log`.

O aplicativo usa os endpoints definidos em `config.local.json`; nao adiciona credenciais ou altera a autenticacao da rede.

## Desenvolvimento e testes

Na pasta `frontend`, `npm run dev` permite visualizar a interface no navegador. Sem a ponte desktop, ela informa **Modo visual** e desabilita consultas e arquivos; nao apresenta dados simulados como reais.

Na raiz:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tests/smoke_desktop.py
```

Na pasta `frontend`:

```powershell
npm test
npm run build
```

Testes automatizados usam HTTP e ponte simulados, sem consultar os sistemas corporativos. Eles nao substituem a homologacao real de rede e dos relatorios.

O smoke desktop abre uma janela WebView2 real, valida a comunicacao JavaScript/Python e fecha automaticamente. Usa perfil temporario e bloqueia consultas externas.

## Gerar aplicativo Windows

O build Cython usa `onedir`. O inicializador desktop,
a API e os extratores continuam compilados como extensoes nativas `.pyd`.
O pequeno `cython_launcher.py` e as bibliotecas de terceiros ainda usam Python
empacotado; Cython dificulta, mas nao impede engenharia reversa.

O EXE carrega as bibliotecas de `_internal`, evitando extrair o runtime em `%TEMP%`
a cada abertura. UPX esta desativado em todos os specs. Temporarios de relatorios
e arquivos do WebView2 continuam fazendo parte da operacao normal. Essas medidas
reduzem fatores de possivel bloqueio, mas nao garantem aceitacao por antivirus,
SmartScreen, Smart App Control ou politicas corporativas.
O build nao gera instalador, atualizacao automatica ou assinatura por padrao.

Requisitos da maquina de build:

- CPython 3.12 x64 no Windows (ABI homologada no lock).
- Visual Studio Build Tools com C++ para desktop e Windows SDK.
- Node.js 22 LTS ou 24 LTS e npm; acesso ao registro de pacotes.

Execute na raiz do projeto:

```powershell
.\build_cython.ps1
# Se necessario, indique o Python 3.12 x64:
.\build_cython.ps1 -Python 'C:\caminho\Python312\python.exe'
```

O script cria/reutiliza `.venv-build`, instala as versoes exatas de
`requirements-build.lock`, verifica se ha pacotes extras/divergentes e executa
`npm ci` com `frontend/package-lock.json`. Depois recompila Cython e PyInstaller
com limpeza do cache. `npm ci` substitui `node_modules`, incluindo caches de teste
que estejam nessa pasta. Se o ambiente Python estiver contaminado, revise e
recrie apenas `.venv-build` antes de compilar novamente.

Saidas:

```text
dist/
  Extrator_SGD/
    Extrator_SGD.exe
    _internal/
    LEIA-ME.txt
    config.local.json
    build-info.json
    SHA256SUMS.txt
  Extrator_SGD-1.2.1-windows-x64.zip
  Extrator_SGD-1.2.1-windows-x64.zip.sha256
```

Distribua o ZIP e seu `.sha256`. O usuario deve extrair a pasta inteira e abrir
o EXE mantendo `_internal` ao lado. Para atualizar, extraia em uma pasta nova e
atualize o atalho; evite misturar bibliotecas antigas e novas. Resultados e
preferencias continuam em `%LOCALAPPDATA%/ExtratorSGD`.

O ZIP e criado exclusivamente a partir de `dist/Extrator_SGD`; nao envie a pasta
do projeto ou o antigo `.7z` com `node_modules` e navegadores de teste. A validacao
da entrega exige os seis modulos nativos, verifica o arquivo interno do EXE e
rejeita implementacoes Python proprias no lugar de Cython e pastas de desenvolvimento.
`build-info.json` registra versao, ferramentas, dependencias, hashes de fontes e
do EXE. `SHA256SUMS.txt` cobre o conteudo da pasta, exceto o proprio manifesto.
O checksum externo cobre o ZIP completo. Para conferir:

```powershell
Get-FileHash .\dist\Extrator_SGD-1.2.1-windows-x64.zip -Algorithm SHA256
```

Compare o resultado com o `.sha256` recebido por um canal confiavel. Esses hashes
nao autenticam o fornecedor e nao substituem assinatura digital. O lock fixa
versoes de pacotes, mas nao promete builds identicos byte a byte: timestamps,
assinatura e toolchain C++ tambem influenciam o resultado.

### Assinatura digital opcional

O build padrao e **sem assinatura**, informado ao final e no `build-info.json`.
Para assinar, use um certificado confiavel de assinatura de codigo com chave
privada acessivel em `Cert:\CurrentUser\My`:

```powershell
.\build_cython.ps1 -CertificateThumbprint 'THUMBPRINT_DO_CERTIFICADO'
```

O script assina o EXE e os seis `.pyd` proprios com SHA-256, exige assinatura
valida e carimbo de tempo e somente depois gera o ZIP e hashes. Bibliotecas de
terceiros preservam suas assinaturas existentes. `-TimestampServer` permite
configurar o servidor de carimbo de tempo (padrao: `http://timestamp.digicert.com`).
Nao ha criacao de certificado autoassinado, nem necessidade de colocar senhas ou
chaves no projeto. A reputacao e as politicas do destino continuam relevantes
mesmo com assinatura valida.

### Homologar a entrega Cython

```powershell
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-build\Scripts\python.exe tests/smoke_desktop.py
.\tests\smoke_packaged.ps1
.\.venv-build\Scripts\python.exe tests/smoke_release.py
```

O smoke PowerShell valida o EXE Cython em pasta, incluindo interface React, ponte
Python e icone. Abre uma janela com perfil temporario, sem iniciar consultas, e
fecha somente o processo criado pelo teste.

`smoke_release.py` confere o SHA-256 do ZIP e de cada arquivo, os metadados de
versao/arquitetura e a estrutura Cython. Em seguida extrai o ZIP em uma pasta
temporaria e executa o mesmo smoke no aplicativo efetivamente distribuido.

Os testes do frontend usam o Microsoft Edge instalado no Windows.

A versao do produto e os nomes dos modulos Cython estao em `build_support.py`.
Ao atualizar dependencias do build, gere/revise o lock em ambiente isolado,
confira compatibilidade com `requirements-dev.txt` e repita a homologacao antes
de publicar. As faixas dos requirements de desenvolvimento nao alteram o lock
automaticamente.
