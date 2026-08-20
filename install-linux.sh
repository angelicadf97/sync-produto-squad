#!/usr/bin/env bash
# Instala as dependências, cria o atalho e configura o início automático no Linux (GNOME).
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== Verificando python3 e gh =="
command -v python3 >/dev/null || { echo "python3 não encontrado. Instale antes de continuar."; exit 1; }
command -v gh >/dev/null || { echo "GitHub CLI (gh) não encontrado. Veja https://cli.github.com e rode 'gh auth login' antes de usar."; exit 1; }

echo "== Instalando dependências Python (usuário) =="
pip install --user -r "$HERE/requirements.txt"

echo "== Instalando suporte a ícone de bandeja (AppIndicator) =="
if ! python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null \
   && ! python3 -c "import gi; gi.require_version('AppIndicator3','0.1'); from gi.repository import AppIndicator3" 2>/dev/null; then
    echo "Vai pedir sua senha de sudo pra instalar o pacote do sistema:"
    sudo apt install -y gir1.2-ayatanaappindicator3-0.1 || sudo apt install -y gir1.2-appindicator3-0.1
else
    echo "Já instalado, ok."
fi

echo "== Criando atalho =="
DESKTOP_FILE="$HERE/Sync Produto x Squad.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Sync Produto x Squad
Comment=Ícone na bandeja pra sincronizar prazos e gerar relatórios
Exec=python3 "$HERE/gui.py"
Icon=utilities-terminal
Terminal=false
Categories=Utility;
EOF
chmod +x "$DESKTOP_FILE"

mkdir -p ~/.local/share/applications ~/.config/autostart
cp "$DESKTOP_FILE" ~/.local/share/applications/sync-produto-squad.desktop
ln -sf "$DESKTOP_FILE" ~/.config/autostart/"Sync Produto x Squad.desktop"
update-desktop-database ~/.local/share/applications 2>/dev/null || true

echo
echo "Pronto! Pra abrir agora sem esperar o próximo login:"
echo "  python3 \"$HERE/gui.py\" &"
echo
echo "Da próxima vez que você logar no computador, o ícone já vai aparecer sozinho na bandeja."
echo "Se ainda não configurou nenhuma squad, rode: python3 \"$HERE/configurar.py\""
