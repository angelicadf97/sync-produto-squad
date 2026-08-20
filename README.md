# Sync Produto x Squad

Sincroniza prazos (Estimativa, Start date, Due date) entre o Project "Produto" e os Projects
de cada squad no GitHub, e gera relatórios de ciclo de vida das issues. Inclui um ícone de
bandeja do sistema (Linux e Windows) pra usar sem terminal.

## Pré-requisitos (nas duas plataformas)

- **Python 3.9+**
- **GitHub CLI** (`gh`) autenticado com escopos `repo` e `project`:
  ```
  gh auth login
  gh auth refresh -s project,read:project
  ```

## Instalar no Linux

```bash
git clone https://github.com/angelicadf97/sync-produto-squad.git
cd sync-produto-squad
./install-linux.sh
```

Isso instala as dependências Python, o suporte a ícone de bandeja (AppIndicator, pode pedir
sua senha de sudo pra um pacote do sistema) e cria o atalho + início automático.

## Instalar no Windows

1. Instale o [Python](https://python.org/downloads) (marque "Add python.exe to PATH" na instalação) e o [GitHub CLI](https://cli.github.com).
2. Baixe/clone este repositório.
3. Dê **duplo clique em `install-windows.bat`** (não no `.ps1` diretamente — o Windows
   bloqueia scripts PowerShell por padrão, e o `.bat` já contorna isso).

Isso instala as dependências e cria um atalho em "Iniciar" + início automático.

> Alternativa avançada: `build-windows.bat` gera arquivos `.exe` standalone via PyInstaller,
> pra quem não quiser depender de Python instalado. Precisa rodar num Windows de verdade.

## Primeiro uso

Depois de instalado (Linux ou Windows), o ícone aparece na bandeja do sistema. Clique nele →
**Configurar / adicionar squad** e siga o assistente: ele pede só o **número** dos Projects
(Produto e o board da squad) e deixa escolher os campos numa lista — nenhum ID técnico.

## O que cada ação faz

- **Ver o que mudaria** — simula a sincronização sem escrever nada.
- **Sincronizar agora** — aplica de verdade: Estimativa e Data de início priorizam o que
  está na Squad; a 1ª entrada em "em desenvolvimento" define a Data de início; o Due date é
  sempre recalculado (Start + Estimativa em dias úteis se aberta, data real de fechamento se
  concluída).
- **Gerar relatório de ciclo de vida (CSV)** — tempo em cada status, prazo, atraso e
  dependências (issues-filhas que também estão no mesmo Project).
- **Corrigir datas de issues fechadas** — ajusta Start/Due date de issues já concluídas pra
  refletir o histórico real (uso pontual, pra saneiar dados antigos).

## Uso por linha de comando (sem a interface)

```bash
python3 sync-prazo.py --squad vox --dry-run
python3 sync-prazo.py --squad vox
python3 tempo-status.py --squad vox --all --csv ciclo-vida.csv
python3 corrige-datas-fechadas.py --squad vox
python3 configurar.py          # assistente de configuração em texto
python3 menu.py                # menu interativo em texto
```

## Estrutura

- `sync-prazo.py` — sincronização diária (Estimativa, Start date, Due date)
- `tempo-status.py` — relatório de ciclo de vida em CSV
- `corrige-datas-fechadas.py` — correção pontual de issues fechadas
- `configurar.py` / `gui.py` (botão "Configurar") — assistente de configuração de squads
- `gui.py` — ícone de bandeja (interface principal)
- `menu.py` — menu em texto, alternativa ao `gui.py` pra quem prefere terminal
- `config.json` — squads configuradas (Project Produto, Project de cada squad, campos)
