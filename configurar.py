#!/usr/bin/env python3
"""Assistente interativo pra configurar um novo squad em config.json — só pede coisas que
você vê na tela do GitHub (número do Project, nome dos campos), nunca IDs internos.

Uso: python3 configurar.py
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "config.json"

spec = importlib.util.spec_from_file_location("sync_prazo", HERE / "sync-prazo.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def choose_field(field_ids, role, examples=""):
    names = sorted(field_ids)
    print(f"\nCampos disponíveis nesse Project:")
    for i, n in enumerate(names, 1):
        print(f"  {i}) {n}")
    hint = f" (ex: {examples})" if examples else ""
    while True:
        raw = ask(f"Qual campo é '{role}'{hint}? (número ou nome exato)")
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        if raw in field_ids:
            return raw
        print("Não encontrei esse campo, tenta de novo.")


def main():
    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {
        "org": "", "default_repo": "", "produto": {}, "squads": {}
    }

    cfg["org"] = ask("Organização do GitHub", cfg.get("org") or "ContatoSeguro")
    cfg["default_repo"] = ask(
        "Repositório padrão (usado só como atalho ao consultar 1 issue pelo número)",
        cfg.get("default_repo") or f"{cfg['org']}/core",
    )

    if cfg["produto"].get("project_number"):
        print(f"\nProject Produto já configurado: #{cfg['produto']['project_number']}")
        if ask("Reconfigurar? (s/N)", "n").lower() != "s":
            reuse_produto = True
        else:
            reuse_produto = False
    else:
        reuse_produto = False

    if not reuse_produto:
        numero = int(ask("Número do Project 'Produto' (o funil de PRD/Épico/US, ex: 43)"))
        _, title, field_ids = sp.resolve_project(cfg["org"], numero)
        print(f"Encontrado: \"{title}\"")
        cfg["produto"] = {
            "project_number": numero,
            "fields": {
                "start": choose_field(field_ids, "Data de início"),
                "due": choose_field(field_ids, "Previsão/Data de entrega"),
                "estimativa": choose_field(field_ids, "Estimativa"),
            },
        }

    print("\n--- Novo squad ---")
    squad_name = ask("Nome curto do squad (slug, ex: vox, orbit)").lower().replace(" ", "-")
    numero = int(ask(f"Número do Project do squad '{squad_name}' (o board de dev, ex: 37)"))
    _, title, field_ids = sp.resolve_project(cfg["org"], numero)
    print(f"Encontrado: \"{title}\"")

    status_field = choose_field(field_ids, "Status")

    # tenta listar as opções do campo de Status pra facilitar escolher o wip_status
    query = f'''
    query {{
      organization(login: "{cfg["org"]}") {{
        projectV2(number: {numero}) {{
          field(name: "{status_field}") {{
            ... on ProjectV2SingleSelectField {{ options {{ name }} }}
          }}
        }}
      }}
    }}
    '''
    data = sp.gh_graphql(query)
    field = (data.get("data") or {}).get("organization", {}).get("projectV2", {}).get("field")
    options = [o["name"] for o in field["options"]] if field and field.get("options") else []

    if options:
        print("\nValores desse campo de Status:")
        for i, o in enumerate(options, 1):
            print(f"  {i}) {o}")
        raw = ask("Qual valor representa 'em desenvolvimento' (dispara o cálculo de prazo)?")
        wip_status = options[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(options) else raw
    else:
        wip_status = ask("Qual o nome exato do status 'em desenvolvimento'?", "WORK IN PROGRESS")

    labels = ask("Labels que identificam uma US (separadas por vírgula)", "feature,bug,task")

    cfg["squads"][squad_name] = {
        "project_number": numero,
        "fields": {
            "start": choose_field(field_ids, "Start date"),
            "due": choose_field(field_ids, "Due date"),
            "estimativa": choose_field(field_ids, "Estimativa"),
            "status": status_field,
        },
        "wip_status": wip_status,
        "us_labels": [l.strip() for l in labels.split(",") if l.strip()],
    }

    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    print(f"\nSalvo em {CONFIG_FILE}. Pra usar: python3 sync-prazo.py --squad {squad_name}")


if __name__ == "__main__":
    main()
