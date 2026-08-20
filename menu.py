#!/usr/bin/env python3
"""Menu interativo — o "botão" pra rodar os scripts sem precisar lembrar os comandos.

Uso: python3 menu.py
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "config.json"


def run(*args):
    print(f"\n$ python3 {' '.join(args)}\n")
    subprocess.run([sys.executable, *args], cwd=HERE)
    input("\n[enter pra voltar ao menu]")


def pick_squad():
    if not CONFIG_FILE.exists():
        print("Nenhum config.json ainda — rode a opção de configurar primeiro.")
        return None
    cfg = json.loads(CONFIG_FILE.read_text())
    squads = list(cfg.get("squads", {}))
    if not squads:
        print("Nenhum squad configurado ainda — rode a opção de configurar primeiro.")
        return None
    if len(squads) == 1:
        return squads[0]
    print("\nSquads configurados:")
    for i, s in enumerate(squads, 1):
        print(f"  {i}) {s}")
    raw = input("Qual squad? (número): ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(squads):
        return squads[int(raw) - 1]
    print("Opção inválida.")
    return None


def main():
    while True:
        print("\n=== Sync Produto x Squad ===")
        print("1) Ver o que mudaria agora (dry-run)")
        print("2) Rodar sincronização de verdade")
        print("3) Gerar relatório de ciclo de vida (CSV)")
        print("4) Corrigir datas de issues já fechadas")
        print("5) Configurar / adicionar um squad")
        print("0) Sair")
        choice = input("\nEscolha: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            squad = pick_squad()
            if squad:
                run("sync-prazo.py", "--squad", squad, "--dry-run")
        elif choice == "2":
            squad = pick_squad()
            if squad:
                run("sync-prazo.py", "--squad", squad)
        elif choice == "3":
            squad = pick_squad()
            if squad:
                nome_arquivo = input("Nome do arquivo CSV [ciclo-vida.csv]: ").strip() or "ciclo-vida.csv"
                run("tempo-status.py", "--squad", squad, "--all", "--csv", nome_arquivo)
        elif choice == "4":
            squad = pick_squad()
            if squad:
                confirm = input("Isso ESCREVE nos Projects reais. Rodar em dry-run primeiro? (S/n): ").strip().lower()
                if confirm != "n":
                    run("corrige-datas-fechadas.py", "--squad", squad, "--dry-run")
                run("corrige-datas-fechadas.py", "--squad", squad)
        elif choice == "5":
            run("configurar.py")
        else:
            print("Opção inválida.")


if __name__ == "__main__":
    main()
