#!/usr/bin/env python3
"""Sincroniza os campos de data entre o Project Produto e o Project de um squad, pra mesma
issue — os Projects reúnem issues de vários repositórios da ContatoSeguro, então tudo aqui
identifica a issue pelo id (ou pelo par repo+número, quando precisa consultar a timeline),
nunca assume um repositório fixo.

Qual Produto/Squad e quais campos usar vem de config.json (rode configurar.py pra criar ou
adicionar um squad) — nada de ID de Project/campo fica hardcoded aqui, tudo é resolvido via
API no início de cada execução a partir do NÚMERO do Project e do NOME dos campos.

Usa um arquivo de estado (sync-prazo-state-<squad>.json) para saber qual lado mudou desde a
última execução, já que a API de Projects v2 não expõe "última atualização" por campo — só
por item.

Uso:
  python3 sync-prazo.py [--squad NOME] [--dry-run]
  (--squad só é obrigatório se o config.json tiver mais de um squad configurado)
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

PRODUTO_ITEMS_QUERY_TMPL = """
query($project: ID!, $cursor: String) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            ... on Issue {
              id
              number
              closed
              closedAt
              repository { nameWithOwner }
            }
          }
          startVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldDateValue { date } }
          dueVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldDateValue { date } }
          estimativaVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldNumberValue { number } }
        }
      }
    }
  }
}
"""

SQUAD_ITEMS_QUERY_TMPL = """
query($project: ID!, $cursor: String) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            ... on Issue {
              id
              number
              closed
              closedAt
              repository { nameWithOwner }
            }
          }
          startVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldDateValue { date } }
          dueVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldDateValue { date } }
          statusVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          estimativaVal: fieldValueByName(name: "%s") { ... on ProjectV2ItemFieldNumberValue { number } }
        }
      }
    }
  }
}
"""

PROJECT_FIELDS_QUERY = """
query {
  organization(login: "%s") {
    projectV2(number: %d) {
      id
      title
      fields(first: 50) { nodes { ... on ProjectV2FieldCommon { id name } } }
    }
  }
}
"""

TIMELINE_WIP_QUERY = """
query {
  repository(owner: "%s", name: "%s") {
    issue(number: %d) {
      timelineItems(first: 250, itemTypes: [PROJECT_V2_ITEM_STATUS_CHANGED_EVENT]) {
        nodes {
          ... on ProjectV2ItemStatusChangedEvent {
            createdAt
            status
            project { number }
          }
        }
      }
    }
  }
}
"""

SET_DATE_MUTATION = """
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "%s"
    itemId: "%s"
    fieldId: "%s"
    value: { date: "%s" }
  }) { projectV2Item { id } }
}
"""

SET_NUMBER_MUTATION = """
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "%s"
    itemId: "%s"
    fieldId: "%s"
    value: { number: %s }
  }) { projectV2Item { id } }
}
"""

CLEAR_FIELD_MUTATION = """
mutation {
  clearProjectV2ItemFieldValue(input: {
    projectId: "%s"
    itemId: "%s"
    fieldId: "%s"
  }) { projectV2Item { id } }
}
"""


def gh_graphql(query):
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def resolve_project(org, number):
    """Devolve (project_node_id, title, {nome_do_campo: field_id}) a partir só do número
    do Project — nenhum ID precisa ser conhecido de antemão."""
    query = PROJECT_FIELDS_QUERY % (org, number)
    data = gh_graphql(query)
    proj = (data.get("data") or {}).get("organization", {}).get("projectV2")
    if proj is None:
        raise SystemExit(f"Project #{number} não encontrado em {org} (confira o número e se seu token tem acesso)")
    field_ids = {f["name"]: f["id"] for f in proj["fields"]["nodes"] if f.get("name")}
    return proj["id"], proj["title"], field_ids


def load_config():
    if not CONFIG_FILE.exists():
        raise SystemExit(f"{CONFIG_FILE} não existe — rode configurar.py primeiro.")
    return json.loads(CONFIG_FILE.read_text())


def pick_squad(cfg, squad_name):
    squads = cfg["squads"]
    if squad_name:
        if squad_name not in squads:
            raise SystemExit(f"Squad '{squad_name}' não está no config.json. Disponíveis: {', '.join(squads)}")
        return squad_name, squads[squad_name]
    if len(squads) == 1:
        return next(iter(squads.items()))
    raise SystemExit(f"Mais de um squad configurado ({', '.join(squads)}) — use --squad <nome>")


def _field_id(field_ids, field_name, side):
    if field_name not in field_ids:
        raise SystemExit(f"Campo '{field_name}' não existe no Project {side} — confira config.json (rode configurar.py de novo se o campo mudou de nome)")
    return field_ids[field_name]


def configure(squad_name=None):
    """Carrega config.json, resolve os IDs de Project/campo via API e preenche as
    constantes globais usadas pelo resto do módulo. Chamado 1x no início da execução."""
    global PRODUTO_PROJECT_ID, SQUAD_PROJECT_ID, SQUAD_PROJECT_NUMBER, SQUAD_NAME, WIP_STATUS
    global FIELD_START_PRODUTO, FIELD_DUE_PRODUTO, FIELD_ESTIMATIVA_PRODUTO
    global FIELD_START_SQUAD, FIELD_DUE_SQUAD, FIELD_ESTIMATIVA_SQUAD
    global PRODUTO_ITEMS_QUERY, SQUAD_ITEMS_QUERY, STATE_FILE
    global SQUAD_PROJECT_TITLE, PRODUTO_PROJECT_TITLE, SQUAD_CONFIG, ORG, DEFAULT_REPO

    cfg = load_config()
    ORG = org = cfg["org"]
    DEFAULT_REPO = cfg.get("default_repo", "")
    SQUAD_NAME, squad_cfg = pick_squad(cfg, squad_name)
    SQUAD_CONFIG = squad_cfg

    PRODUTO_PROJECT_ID, PRODUTO_PROJECT_TITLE, produto_field_ids = resolve_project(org, cfg["produto"]["project_number"])
    SQUAD_PROJECT_ID, SQUAD_PROJECT_TITLE, squad_field_ids = resolve_project(org, squad_cfg["project_number"])
    SQUAD_PROJECT_NUMBER = squad_cfg["project_number"]
    WIP_STATUS = squad_cfg.get("wip_status", "WORK IN PROGRESS")

    pf, sf = cfg["produto"]["fields"], squad_cfg["fields"]
    FIELD_START_PRODUTO = _field_id(produto_field_ids, pf["start"], "Produto")
    FIELD_DUE_PRODUTO = _field_id(produto_field_ids, pf["due"], "Produto")
    FIELD_ESTIMATIVA_PRODUTO = _field_id(produto_field_ids, pf["estimativa"], "Produto")
    FIELD_START_SQUAD = _field_id(squad_field_ids, sf["start"], f"Squad ({SQUAD_NAME})")
    FIELD_DUE_SQUAD = _field_id(squad_field_ids, sf["due"], f"Squad ({SQUAD_NAME})")
    FIELD_ESTIMATIVA_SQUAD = _field_id(squad_field_ids, sf["estimativa"], f"Squad ({SQUAD_NAME})")

    PRODUTO_ITEMS_QUERY = PRODUTO_ITEMS_QUERY_TMPL % (pf["start"], pf["due"], pf["estimativa"])
    SQUAD_ITEMS_QUERY = SQUAD_ITEMS_QUERY_TMPL % (sf["start"], sf["due"], sf["status"], sf["estimativa"])
    STATE_FILE = Path(__file__).parent / f"sync-prazo-state-{SQUAD_NAME}.json"


def _fetch_items(project_id, query_template, extra_fields):
    items = {}
    cursor = "null"
    while True:
        query = query_template.replace(
            "$project: ID!, $cursor: String", ""
        ).replace("$project", f'"{project_id}"').replace(
            "after: $cursor", f"after: {cursor}"
        )
        data = gh_graphql(query)
        page = data["data"]["node"]["items"]
        for node in page["nodes"]:
            content = node.get("content")
            if not content:
                continue
            issue_id = content["id"]
            items[issue_id] = {
                "itemId": node["id"],
                "number": content["number"],
                "repo": content["repository"]["nameWithOwner"],
                "closed": content["closed"],
                "closedAt": content.get("closedAt"),
                "start": (node.get("startVal") or {}).get("date"),
                "due": (node.get("dueVal") or {}).get("date"),
                "estimativa": (node.get("estimativaVal") or {}).get("number"),
                **{k: getter(node) for k, getter in extra_fields.items()},
            }
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = f'"{page["pageInfo"]["endCursor"]}"'
    return items


def fetch_produto_items():
    return _fetch_items(PRODUTO_PROJECT_ID, PRODUTO_ITEMS_QUERY, {})


def fetch_squad_items():
    return _fetch_items(SQUAD_PROJECT_ID, SQUAD_ITEMS_QUERY, {
        "status": lambda node: (node.get("statusVal") or {}).get("name"),
    })


def fetch_first_wip_date(repo, number):
    owner, name = repo.split("/", 1)
    query = TIMELINE_WIP_QUERY % (owner, name, number)
    data = gh_graphql(query)
    nodes = data["data"]["repository"]["issue"]["timelineItems"]["nodes"]
    wip_events = [
        n for n in nodes
        if n["status"] == WIP_STATUS and n["project"] and n["project"]["number"] == SQUAD_PROJECT_NUMBER
    ]
    if not wip_events:
        return None
    wip_events.sort(key=lambda e: e["createdAt"])
    return wip_events[0]["createdAt"][:10]


def add_business_days(start, n):
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


DRY_RUN = "--dry-run" in sys.argv


def apply_value(project_id, item_id, field_id, value, kind="date", number=None):
    """number é só pra emitir o marcador ::WRITE:<number> — uma interface (gui.py) usa
    isso pra contar/acompanhar quantas issues são tocadas, sem precisar adivinhar isso
    fazendo parsing das mensagens legíveis por humano."""
    if number is not None:
        print(f"::WRITE:{number}")
    if DRY_RUN:
        print(f"  [dry-run] escreveria {value!r} (item={item_id}, field={field_id})")
        return
    if value is None:
        mutation = CLEAR_FIELD_MUTATION % (project_id, item_id, field_id)
    elif kind == "number":
        mutation = SET_NUMBER_MUTATION % (project_id, item_id, field_id, value)
    else:
        mutation = SET_DATE_MUTATION % (project_id, item_id, field_id, value)
    gh_graphql(mutation)


def squad_wins_sync(number, produto_item_id, squad_item_id,
                     produto_val, squad_val,
                     produto_field_id, squad_field_id, label, kind="date"):
    """A Squad é a origem da verdade pra Estimativa e Data de início — ela reflete a
    realidade operacional melhor que o Produto. Se os dois têm valor e divergem, a Squad
    sempre ganha e o Produto é atualizado. Só quando a Squad está vazia é que copiamos
    do Produto (bootstrap de issue nova)."""
    if produto_val == squad_val:
        return produto_val

    if squad_val is not None:
        print(f"#{number}: {label} = {squad_val} na Squad (prioridade) -> propagando pro Produto (era {produto_val})")
        apply_value(PRODUTO_PROJECT_ID, produto_item_id, produto_field_id, squad_val, kind, number)
        return squad_val

    print(f"#{number}: {label} só existe no Produto ({produto_val}) -> copiando pra Squad (ainda vazia)")
    apply_value(SQUAD_PROJECT_ID, squad_item_id, squad_field_id, produto_val, kind, number)
    return produto_val


def apply_wip_trigger(s, already_started):
    """Só dispara na 1a entrada em WORK IN PROGRESS que a issue já teve (olhando o histórico
    completo, não o status no momento da execução) — pega mesmo quem já saiu do WIP entre
    uma rodada e outra do script. Nunca sobrescreve Start date já preenchido — cobre ajuste
    manual e issues antigas que já tinham essa data antes dessa automação existir.
    Due date não é setado aqui: é sempre recalculado depois, em update_due_date()."""
    if already_started:
        return True

    wip_date_str = fetch_first_wip_date(s["repo"], s["number"])
    if not wip_date_str:
        return False

    if s["start"]:
        print(f"#{s['number']}: já passou por WORK IN PROGRESS ({wip_date_str}) mas Start date já está preenchido ({s['start']}) -> não sobrescrevendo, só marcando como processado")
        return True

    print(f"#{s['number']}: entrou em WORK IN PROGRESS em {wip_date_str} (1a vez) -> Start date = {wip_date_str}")
    apply_value(SQUAD_PROJECT_ID, s["itemId"], FIELD_START_SQUAD, wip_date_str, number=s["number"])
    s["start"] = wip_date_str
    return True


def update_due_date(number, produto_item_id, squad_item_id, closed, closed_at, start, estimativa,
                     produto_due, squad_due):
    """Due date é sempre derivado, nunca editado manualmente:
    - issue fechada -> Due = data real de fechamento (sobrepõe qualquer cálculo)
    - issue aberta -> Due = Start + Estimativa em dias úteis, recalculado sempre que
      Start ou Estimativa mudarem (ex: você adianta/atrasa a Start date manualmente)
    Sem Start ou sem Estimativa (issue aberta) -> não há como calcular, não altera nada.

    Proteção contra regressão: se o cálculo puro (Start + Estimativa) já cair no passado
    E a Due date atual for mais generosa que esse cálculo, significa que a issue já está
    atrasada e alguém (ou uma correção anterior) já assumiu um prazo maior — nesse caso
    não regredimos a Due date pra uma data que já passou, mantemos a atual."""
    if closed:
        target = closed_at[:10]
        reason = f"issue fechada em {target}"
    elif start and estimativa:
        computed = add_business_days(date.fromisoformat(start), round(estimativa))
        current_due = squad_due if squad_due is not None else produto_due
        if computed < date.today() and current_due and date.fromisoformat(current_due) > computed:
            print(f"#{number}: cálculo Start+Estimativa ({computed.isoformat()}) já estaria atrasado e é anterior à Due date atual ({current_due}) -> mantendo Due date atual")
            target = current_due
            reason = f"mantendo prazo já assumido ({current_due}), cálculo puro regrediria pra {computed.isoformat()}"
        else:
            target = computed.isoformat()
            reason = f"Start={start} + Estimativa={estimativa} dias úteis"
    else:
        return None

    if squad_due != target:
        print(f"#{number}: Due date (Squad) {squad_due!r} -> {target} ({reason})")
        apply_value(SQUAD_PROJECT_ID, squad_item_id, FIELD_DUE_SQUAD, target, number=number)
    if produto_due != target:
        print(f"#{number}: Previsão de lançamento (Produto) {produto_due!r} -> {target} ({reason})")
        apply_value(PRODUTO_PROJECT_ID, produto_item_id, FIELD_DUE_PRODUTO, target, number=number)
    return target


def _arg_value(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else None


def cli_resolve_fields():
    """Modo usado pelo assistente de configuração (gui.py/configurar.py) via subprocesso:
    imprime {"title", "fields"} em JSON e sai — não depende de config.json existir."""
    org, number = sys.argv[2], sys.argv[3]
    _, title, field_ids = resolve_project(org, int(number))
    print(json.dumps({"title": title, "fields": sorted(field_ids)}))


def cli_status_options():
    """Idem, mas lista os valores de um campo de single-select (pra escolher o wip_status)."""
    org, number, field_name = sys.argv[2], sys.argv[3], sys.argv[4]
    query = f'''
    query {{
      organization(login: "{org}") {{
        projectV2(number: {int(number)}) {{
          field(name: "{field_name}") {{
            ... on ProjectV2SingleSelectField {{ options {{ name }} }}
          }}
        }}
      }}
    }}
    '''
    data = gh_graphql(query)
    field = (data.get("data") or {}).get("organization", {}).get("projectV2", {}).get("field")
    options = [o["name"] for o in field["options"]] if field and field.get("options") else []
    print(json.dumps({"options": options}))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--resolve-fields":
        return cli_resolve_fields()
    if len(sys.argv) > 1 and sys.argv[1] == "--status-options":
        return cli_status_options()

    configure(_arg_value("--squad"))
    print(f"Squad: {SQUAD_NAME} (Project #{SQUAD_PROJECT_NUMBER}) | estado: {STATE_FILE.name}\n")

    produto_items = fetch_produto_items()
    squad_items = fetch_squad_items()

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    new_state = {}

    matched = set(produto_items) & set(squad_items)

    # 1) Estimativa: Squad é a origem da verdade.
    for issue_id in matched:
        p = produto_items[issue_id]
        s = squad_items[issue_id]
        estimativa = squad_wins_sync(
            p["number"], p["itemId"], s["itemId"],
            p["estimativa"], s["estimativa"],
            FIELD_ESTIMATIVA_PRODUTO, FIELD_ESTIMATIVA_SQUAD, "Estimativa", kind="number",
        )
        p["estimativa"] = s["estimativa"] = estimativa
        new_state.setdefault(issue_id, {})["number"] = p["number"]

    # 2) Gatilho de WIP: só dispara na 1a entrada em WORK IN PROGRESS de cada issue.
    for issue_id, s in squad_items.items():
        prev = state.get(issue_id, {})
        wip_started = apply_wip_trigger(s, prev.get("wip_started", False))
        new_state.setdefault(issue_id, {})["wip_started"] = wip_started

    # 3) Data de início: Squad é a origem da verdade (inclui o que o gatilho de WIP
    # acabou de escrever). Due date é sempre recalculado a partir dela.
    for issue_id in matched:
        p = produto_items[issue_id]
        s = squad_items[issue_id]

        start = squad_wins_sync(
            p["number"], p["itemId"], s["itemId"],
            p["start"], s["start"],
            FIELD_START_PRODUTO, FIELD_START_SQUAD, "Data de início",
        )

        update_due_date(
            p["number"], p["itemId"], s["itemId"],
            p["closed"], p["closedAt"], start, s["estimativa"],
            p["due"], s["due"],
        )

        new_state[issue_id]["number"] = p["number"]

    only_produto = set(produto_items) - set(squad_items)
    only_squad = set(squad_items) - set(produto_items)
    if only_produto:
        print(f"{len(only_produto)} issue(s) só no Project Produto (fora da Squad ainda)")
    if only_squad:
        print(f"{len(only_squad)} issue(s) só no Project Squad (fora do Produto)")

    if DRY_RUN:
        print("\n[dry-run] estado não foi salvo")
    else:
        STATE_FILE.write_text(json.dumps(new_state, indent=2, ensure_ascii=False))
        print(f"\nEstado salvo em {STATE_FILE}")


if __name__ == "__main__":
    main()
