#!/usr/bin/env python3
"""Correção retroativa, pontual: para TODAS as issues já fechadas no Project Vox (com ou
sem label), corrige:
  - Start date  = data real da 1a entrada em WORK IN PROGRESS (via histórico da timeline)
  - Due date    = data real de fechamento da issue
Sobrescreve mesmo que os campos já estejam preenchidos com outro valor — o histórico do
GitHub é a fonte da verdade aqui. Propaga a correção pro Project Produto quando a issue
existir nos dois. Depois de rodar, marca a issue como já processada no estado do
sync-prazo.py, pra ele não tentar mexer de novo.

Uso: python3 corrige-datas-fechadas.py [--squad NOME] [--dry-run]
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = load_module("sync_prazo", "sync-prazo.py")

DRY_RUN = "--dry-run" in sys.argv


def apply(project_id, item_id, field_id, value, label):
    if DRY_RUN:
        print(f"    [dry-run] {label} = {value!r}")
        return
    sp.apply_value(project_id, item_id, field_id, value)


def _arg_value(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else None


def main():
    sp.configure(_arg_value("--squad"))
    print(f"Squad: {sp.SQUAD_NAME} (Project #{sp.SQUAD_PROJECT_NUMBER})\n")

    squad_items = sp.fetch_squad_items()
    produto_items = sp.fetch_produto_items()
    state = json.loads(sp.STATE_FILE.read_text()) if sp.STATE_FILE.exists() else {}

    closed = {issue_id: s for issue_id, s in squad_items.items() if s["closed"]}
    print(f"{len(closed)} issue(s) fechada(s) no Project {sp.SQUAD_NAME}")

    fixed_start = fixed_due = 0
    for issue_id, s in closed.items():
        p = produto_items.get(issue_id)
        due_target = s["closedAt"][:10]
        wip_target = sp.fetch_first_wip_date(s["repo"], s["number"])

        if wip_target and s["start"] != wip_target:
            print(f"#{s['number']}: Start date {s['start']!r} -> {wip_target} (1a entrada em {sp.WIP_STATUS})")
            apply(sp.SQUAD_PROJECT_ID, s["itemId"], sp.FIELD_START_SQUAD, wip_target, "Start date")
            if p:
                apply(sp.PRODUTO_PROJECT_ID, p["itemId"], sp.FIELD_START_PRODUTO, wip_target, "Data de início")
            s["start"] = wip_target
            fixed_start += 1
        elif not wip_target:
            print(f"#{s['number']}: nunca passou por {sp.WIP_STATUS} na timeline, Start date não corrigido")

        if s["due"] != due_target:
            print(f"#{s['number']}: Due date {s['due']!r} -> {due_target} (data de fechamento real)")
            apply(sp.SQUAD_PROJECT_ID, s["itemId"], sp.FIELD_DUE_SQUAD, due_target, "Due date")
            if p:
                apply(sp.PRODUTO_PROJECT_ID, p["itemId"], sp.FIELD_DUE_PRODUTO, due_target, "Previsão de lançamento")
            s["due"] = due_target
            fixed_due += 1

        if not DRY_RUN:
            state.setdefault(issue_id, {}).update({"number": s["number"], "wip_started": True})

    print(f"\n{fixed_start} Start date(s) corrigido(s), {fixed_due} Due date(s) corrigido(s)")

    if DRY_RUN:
        print("[dry-run] estado não foi salvo")
    else:
        sp.STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        print(f"Estado salvo em {sp.STATE_FILE}")


if __name__ == "__main__":
    main()
