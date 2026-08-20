#!/usr/bin/env python3
"""Calcula o tempo que cada issue do Project Vox passou em cada status, usando o histórico
real de trocas (PROJECT_V2_ITEM_STATUS_CHANGED_EVENT) na timeline da issue. O Project Vox
reúne issues de vários repositórios da ContatoSeguro (core, portal-frontend, product-env,
etc.) — número de issue não é único entre repos, então toda issue é identificada pelo par
repo+número.

--all busca as issues do Project Vox (#37), de qualquer repositório, com label feature, bug
ou task (as issues de US) — as demais (sem essas labels) não entram no relatório.

Uso:
  python3 tempo-status.py 13500 13584                     # assume ContatoSeguro/core
  python3 tempo-status.py ContatoSeguro/portal-frontend#421  # issue de outro repo
  python3 tempo-status.py --all                     # US do Vox (label feature/bug/task)
  python3 tempo-status.py --all --since 2026-08-01  # só issues abertas, ou concluídas
                                                      # dentro do período (until = hoje)
  python3 tempo-status.py --all --since 2026-08-01 --until 2026-08-15
  python3 tempo-status.py --all --csv ciclo-vida.csv  # relatório de ciclo de vida em CSV
                                                        # (Start/Due/Estimativa/atraso +
                                                        # tempo em cada status do Vox)
"""
import csv
import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

VOX_STATUSES = [
    "BACKLOG", "TO DO", "WORK IN PROGRESS", "AWAITING CODE REVIEW",
    "CODE REVIEW IN PROGRESS", "AWAITING DEV VALIDATION", "DEV VALIDATION IN PROGRESS",
    "AWAITING UAT", "UAT IN PROGRESS", "AWAITING RELEASE", "DONE",
]

_sp = None


def sync_prazo(squad_name=None):
    """Carrega e configura sync-prazo.py (mesma config.json/squad) — reusa
    SQUAD_PROJECT_ID/SQUAD_PROJECT_TITLE/fetch_squad_items/add_business_days em vez de
    duplicar essa lógica aqui."""
    global _sp
    if _sp is None:
        spec = importlib.util.spec_from_file_location("sync_prazo", Path(__file__).parent / "sync-prazo.py")
        _sp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_sp)
        _sp.configure(squad_name)
    return _sp

NUMBERS_QUERY = """
query($project: ID!, $cursor: String) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content {
            ... on Issue {
              number
              closed
              closedAt
              labels(first: 10) { nodes { name } }
              repository { nameWithOwner }
            }
          }
        }
      }
    }
  }
}
"""

TIMELINE_QUERY = """
query {
  repository(owner: "%s", name: "%s") {
    issue(number: %d) {
      title
      timelineItems(first: 250, itemTypes: [PROJECT_V2_ITEM_STATUS_CHANGED_EVENT]) {
        nodes {
          ... on ProjectV2ItemStatusChangedEvent {
            createdAt
            previousStatus
            status
            project { title }
          }
        }
      }
      subIssues(first: 25) {
        nodes {
          number
          title
          closed
          closedAt
          repository { nameWithOwner }
        }
      }
    }
  }
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


def fetch_all_issues(squad_name=None):
    """Issues do Project do squad configurado, de qualquer repositório (US = tem uma das
    labels em us_labels do config.json). Chave = (repo, number), porque número de issue
    repete entre repositórios."""
    sp = sync_prazo(squad_name)
    us_labels = set(sp.SQUAD_CONFIG.get("us_labels", []))
    issues = {}
    cursor = "null"
    while True:
        query = NUMBERS_QUERY.replace(
            "$project: ID!, $cursor: String", ""
        ).replace("$project", f'"{sp.SQUAD_PROJECT_ID}"').replace(
            "after: $cursor", f"after: {cursor}"
        )
        data = gh_graphql(query)
        page = data["data"]["node"]["items"]
        for node in page["nodes"]:
            content = node.get("content")
            if not content:
                continue
            labels = {n["name"] for n in content["labels"]["nodes"]}
            if us_labels and not labels & us_labels:
                continue
            key = (content["repository"]["nameWithOwner"], content["number"])
            issues[key] = {
                "closed": content["closed"],
                "closedAt": content.get("closedAt"),
            }
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = f'"{page["pageInfo"]["endCursor"]}"'
    return issues


def filter_by_period(issues, since, until):
    """Mantém issues abertas (independente de quando começaram) + issues concluídas
    dentro do período [since, until]."""
    kept = []
    for key, info in issues.items():
        if not info["closed"]:
            kept.append(key)
            continue
        closed_date = date.fromisoformat(info["closedAt"][:10])
        if since <= closed_date <= until:
            kept.append(key)
    return sorted(kept)


def fetch_events(repo, number):
    owner, name = repo.split("/", 1)
    query = TIMELINE_QUERY % (owner, name, number)
    data = gh_graphql(query)
    issue = data["data"]["repository"]["issue"]
    if issue is None:
        return None, [], []
    events = [
        {
            "createdAt": datetime.fromisoformat(n["createdAt"].replace("Z", "+00:00")),
            "previousStatus": n["previousStatus"],
            "status": n["status"],
            "project": n["project"]["title"] if n["project"] else "?",
        }
        for n in issue["timelineItems"]["nodes"]
    ]
    events.sort(key=lambda e: e["createdAt"])
    sub_issues = [
        {
            "repo": n["repository"]["nameWithOwner"],
            "number": n["number"],
            "title": n["title"],
            "closed": n["closed"],
            "closedAt": n.get("closedAt"),
        }
        for n in issue["subIssues"]["nodes"]
    ]
    return issue["title"], events, sub_issues


def child_summary(repo, number, closed, closed_at):
    """Resumo de uma issue-dependência (filha): só conta se ela também estiver, ela mesma,
    no Project do squad configurado — dependência que mora só em outro board
    (frontend/backend com board próprio) ou em nenhum project não entra no relatório."""
    sp = sync_prazo()
    title, events, _ = fetch_events(repo, number)
    now = datetime.now(timezone.utc)
    totals, current_status = status_totals_by_project(events, now).get(sp.SQUAD_PROJECT_TITLE, (None, None))
    if totals is None:
        return {
            "titulo": title or "", "status_atual": f"(fora do Project {sp.SQUAD_NAME})", "projeto": "",
            "ciclo_total_dias": None,
        }
    total_dias = sum(totals.values()) / 86400
    return {
        "titulo": title, "status_atual": current_status, "projeto": sp.SQUAD_PROJECT_TITLE,
        "ciclo_total_dias": round(total_dias, 2),
    }


def fmt_duration(delta):
    total_minutes = int(delta.total_seconds() // 60)
    days, rem = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if not days and not hours:
        parts.append(f"{minutes}min")
    return " ".join(parts) or "0min"


def status_totals_by_project(events, now):
    """{project: (totals_em_segundos_por_status, status_atual)}"""
    by_project = {}
    for e in events:
        by_project.setdefault(e["project"], []).append(e)

    result = {}
    for project, evs in by_project.items():
        totals = {}
        for i, e in enumerate(evs):
            end = evs[i + 1]["createdAt"] if i + 1 < len(evs) else now
            duration = (end - e["createdAt"]).total_seconds()
            totals[e["status"]] = totals.get(e["status"], 0) + duration
        result[project] = (totals, evs[-1]["status"])
    return result


def report(repo, number):
    title, events, _ = fetch_events(repo, number)
    if title is None:
        print(f"{repo}#{number}: issue não encontrada")
        return
    print(f"\n{repo}#{number} - {title}")
    if not events:
        print("  (sem histórico de mudança de status registrado)")
        return

    now = datetime.now(timezone.utc)
    for project, (totals, current_status) in status_totals_by_project(events, now).items():
        from datetime import timedelta
        print(f"  [{project}]")
        for status, secs in sorted(totals.items(), key=lambda kv: -kv[1]):
            marker = " (atual, em andamento)" if status == current_status else ""
            print(f"    {status}: {fmt_duration(timedelta(seconds=secs))}{marker}")


def lifecycle_row(repo, number, s):
    """Uma linha do relatório de ciclo de vida: dados de prazo (sync-prazo.py) +
    tempo em cada status do Vox (timeline). s = item do fetch_squad_items."""
    sp = sync_prazo()
    title, events, sub_issues = fetch_events(repo, number)
    now = datetime.now(timezone.utc)
    totals, current_status = status_totals_by_project(events, now).get(sp.SQUAD_PROJECT_TITLE, ({}, s["status"]))

    start = s["start"]
    estimativa = s["estimativa"]
    closed = s["closed"]
    closed_at = date.fromisoformat(s["closedAt"][:10]) if closed else None

    prazo_calculado = None
    atraso_dias = ""
    if start and estimativa:
        prazo_calculado = sp.add_business_days(date.fromisoformat(start), round(estimativa))
        referencia = closed_at if closed else date.today()
        atraso_dias = (referencia - prazo_calculado).days

    ciclo_total_dias = round(sum(totals.values()) / 86400, 2)
    row = {
        "tipo": "US",
        "issue_pai": "",
        "repo": repo,
        "numero": number,
        "titulo": title or "",
        "projeto_item": sp.SQUAD_PROJECT_TITLE,
        "status_atual": current_status,
        "start_date": start or "",
        "estimativa_dias_uteis": estimativa or "",
        "prazo_calculado": prazo_calculado.isoformat() if prazo_calculado else "",
        "due_date": s["due"] or "",
        "fechada": "sim" if closed else "não",
        "data_fechamento": closed_at.isoformat() if closed_at else "",
        "atraso_dias": atraso_dias,
    }
    for status in VOX_STATUSES:
        row[status] = round(totals.get(status, 0) / 86400, 2)
    row["ciclo_total_dias"] = ciclo_total_dias
    return row, sub_issues


def dependency_row(parent_repo, parent_number, child):
    """Linha de uma issue-dependência (filha da US) — a maioria não está em nenhum Project
    e por isso não tem tempo medido; as que estão (ex: a frontend enquanto a US é a
    backend) entram com o próprio ciclo, pra somar no tempo real da US."""
    summary = child_summary(child["repo"], child["number"], child["closed"], child["closedAt"])
    closed_at = date.fromisoformat(child["closedAt"][:10]) if child["closed"] and child["closedAt"] else None
    row = {
        "tipo": "dependência",
        "issue_pai": f"{parent_repo}#{parent_number}",
        "repo": child["repo"],
        "numero": child["number"],
        "titulo": summary["titulo"] or child["title"],
        "projeto_item": summary["projeto"],
        "status_atual": summary["status_atual"],
        "start_date": "", "estimativa_dias_uteis": "", "prazo_calculado": "", "due_date": "",
        "fechada": "sim" if child["closed"] else "não",
        "data_fechamento": closed_at.isoformat() if closed_at else "",
        "atraso_dias": "",
    }
    for status in VOX_STATUSES:
        row[status] = ""
    row["ciclo_total_dias"] = summary["ciclo_total_dias"] if summary["ciclo_total_dias"] is not None else ""
    return row


def write_csv(keys, path):
    sp = sync_prazo()
    squad_items = sp.fetch_squad_items()
    by_key = {(s["repo"], s["number"]): s for s in squad_items.values()}

    fieldnames = [
        "tipo", "issue_pai", "repo", "numero", "titulo", "projeto_item", "status_atual",
        "start_date", "estimativa_dias_uteis", "prazo_calculado", "due_date", "fechada",
        "data_fechamento", "atraso_dias", *VOX_STATUSES, "ciclo_total_dias",
        "tempo_total_somado_dias", "qtd_dependencias", "qtd_dependencias_medidas",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, (repo, number) in enumerate(keys, 1):
            print(f"[{i}/{len(keys)}] {repo}#{number}", flush=True)
            s = by_key.get((repo, number))
            if s is None:
                print(f"{repo}#{number}: não encontrada no Project Vox, pulando")
                continue
            parent_row, sub_issues = lifecycle_row(repo, number, s)

            all_child_rows = [dependency_row(repo, number, child) for child in sub_issues]
            child_rows = [r for r in all_child_rows if r["ciclo_total_dias"] != ""]
            medidas = [r["ciclo_total_dias"] for r in child_rows]

            parent_row["qtd_dependencias"] = len(sub_issues)
            parent_row["qtd_dependencias_medidas"] = len(medidas)
            parent_row["tempo_total_somado_dias"] = round(parent_row["ciclo_total_dias"] + sum(medidas), 2)

            writer.writerow(parent_row)
            for child_row in child_rows:
                writer.writerow(child_row)
    print(f"\nCSV salvo em {path} ({len(keys)} US + dependências)")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    squad_name = None
    if "--squad" in args:
        i = args.index("--squad")
        squad_name = args[i + 1]
        args = args[:i] + args[i + 2:]

    if "--all" in args:
        issues = fetch_all_issues(squad_name)
        sp = sync_prazo(squad_name)
        if "--since" in args:
            since = date.fromisoformat(args[args.index("--since") + 1])
            until = date.today()
            if "--until" in args:
                until = date.fromisoformat(args[args.index("--until") + 1])
            keys = filter_by_period(issues, since, until)
            print(f"{len(keys)} issue(s) abertas ou concluídas entre {since} e {until} (de {len(issues)} no total)")
        else:
            keys = sorted(issues)
            print(f"{len(keys)} issue(s) de US encontradas no Project {sp.SQUAD_NAME}")

        if "--csv" in args:
            write_csv(keys, args[args.index("--csv") + 1])
        else:
            for repo, number in keys:
                report(repo, number)
    else:
        sp = sync_prazo(squad_name)
        for arg in args:
            if "#" in arg:
                repo, number = arg.split("#")
            else:
                repo, number = sp.DEFAULT_REPO, arg
                print(f"(assumindo {sp.DEFAULT_REPO} — use owner/repo#numero pra outro repositório)")
            report(repo, int(number))


if __name__ == "__main__":
    main()
