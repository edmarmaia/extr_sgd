# Extrator SGD - Aplicativo Windows

## Abrir

1. Antes de extrair, clique com o botao direito no ZIP, abra Propriedades e, se
   aparecer a opcao Desbloquear, marque-a e confirme.
2. Extraia todo o ZIP para uma pasta local.
3. Abra Extrator_SGD.exe dentro da pasta Extrator_SGD.
4. Mantenha a pasta _internal, Extrator_SGD.exe.config e config.local.json ao lado
   do EXE. Eles contem as bibliotecas, a interface e a configuracao do ambiente.

Requisitos: Windows x64, Microsoft Edge WebView2 Runtime e acesso aos sistemas
corporativos pela rede/VPN. Python, Node.js e Excel nao precisam estar instalados.
Para facilitar o acesso, crie um atalho para o EXE; nao mova somente o executavel.

Se aparecer "Failed to resolve Python.Runtime.Loader.Initialize", o Windows
bloqueou as DLLs extraidas. Desbloqueie o ZIP original e extraia novamente. Como
alternativa, extraia com 7-Zip ou execute `Get-ChildItem -Recurse | Unblock-File`
no PowerShell dentro da pasta do aplicativo. Esse erro nao indica falha do
WebView2.

## Atualizar

Feche o aplicativo e extraia a nova versao em uma pasta nova. Abra o novo EXE e,
se usar atalho, atualize seu destino. Isso evita misturar bibliotecas de versoes
diferentes. Resultados e preferencias continuam em %LOCALAPPDATA%\ExtratorSGD.

## Dados e suporte

Em Localizar programacao, informe departamento e periodo e preencha Empresa ou
Identificador OT/ORDEM. Empresa busca parte do nome na coluna Empresa Realizadora,
ignorando maiusculas e acentos, e permite deixar o identificador vazio. Se informar
ambos, os dois filtros sao aplicados. Todas as correspondencias do departamento e
periodo consultados aparecem nos resultados e podem ser exportadas para Excel.

Estado e Status usam as mesmas cores e o filtro de status da tabela. Datas de
consulta e atualizacao sao exibidas no horario local do computador. "Dados
atualizados em" muda quando novos resultados sao publicados, permanecendo fixo
apos a conclusao e durante a espera entre ciclos do monitoramento.

Lotes e monitoramento salvam copias em %LOCALAPPDATA%\ExtratorSGD\results.
Use Exportar Excel para escolher outro destino. Os arquivos podem conter dados
corporativos. O log do desktop fica em %LOCALAPPDATA%\ExtratorSGD\desktop.log.

build-info.json informa versao, dependencias, hash do EXE e se esta entrega foi
assinada. SHA256SUMS.txt lista os hashes dos arquivos (exceto o proprio manifesto).
O .zip.sha256 entregue separadamente permite conferir o ZIP com Get-FileHash.
Hashes verificam integridade em comparacao com uma referencia confiavel; nao
substituem uma assinatura digital.

Os modulos da aplicacao sao compilados com Cython e carregados da pasta _internal.
O EXE nao extrai o runtime Python a cada abertura. Arquivos temporarios de trabalho
e o perfil do WebView2 ainda sao usados normalmente. Esse formato pode reduzir
fatores de bloqueio, mas a aceitacao depende da protecao e das politicas do computador.

`config.local.json` contem enderecos e identificadores do ambiente. Distribua esse
arquivo somente pelos canais internos autorizados e nao o publique em repositorios.
